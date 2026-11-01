"""聊天接口：默认知识库问答，可显式选择普通聊天。"""
import datetime
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import sqlite3
from configs.settings import settings
from src.database.conversations import ConversationError

from src.api.deps import get_llm_dependency
from src.llm.llm_client import MultiLLMClient
from src.prompts.chat_system_prompt import CHAT_SYSTEM_PROMPT
from src.workflow.rag_chat import ServiceUnavailable, UpstreamError

logger = logging.getLogger(__name__)
router = APIRouter()
_BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_input: str = Field(min_length=1, max_length=settings.chat_question_chars)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_location: dict[str, Any] | None = None
    mode: Literal["rag", "chat"] = "rag"
    top_k: int = Field(default=4, ge=1, le=100, strict=True)
    min_score: float = Field(default=0.2, ge=-1, le=1, allow_inf_nan=False)
    document_ids: list[str] | None = None

    @model_validator(mode='after')
    def paired_ids(self):
        if (self.conversation_id is None) != (self.request_id is None):
            raise ValueError('conversation_id 和 request_id 必须同时提供')
        return self

    @field_validator("user_input")
    @classmethod
    def nonempty_question(cls, value):
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()

    @field_validator("document_ids")
    @classmethod
    def nonempty_ids(cls, value):
        if value is not None and any(not item.strip() for item in value):
            raise ValueError("文档 ID 不能为空")
        return value


class Citation(BaseModel):
    number: int
    chunk_id: str
    document_id: str
    ingestion_id: str
    filename: str
    chunk_index: int
    text: str
    score: float
    metadata: dict[str, Any]


class ChatResponse(BaseModel):
    sucess: bool  # 保留现有字段拼写以兼容调用方
    code: int
    message: str
    data: str
    timestamp: str
    mode: Literal["rag", "chat"]
    citations: list[Citation] = Field(default_factory=list)
    conversation_id: str | None = None
    request_id: str | None = None
    history_turns: int = 0
    used_summary: bool = False


@router.post("/chat", response_model=ChatResponse, summary="聊天与知识库问答")
async def chat(request: ChatRequest, http_request: Request, response: Response,
               llm_client: MultiLLMClient = Depends(get_llm_dependency)) -> ChatResponse:
    timestamp = datetime.datetime.now(_BEIJING_TZ).isoformat()
    try:
        if request.conversation_id is not None:
            service = getattr(http_request.app.state, 'conversation_chat', None)
            if service is None:
                raise ServiceUnavailable('会话服务尚未就绪')
            payload = request.model_dump(exclude={'conversation_id', 'request_id'})
            result = await service.answer(request.conversation_id, request.request_id, payload,
                                          getattr(http_request.app.state, 'rag_chat', None))
            return ChatResponse(**result)
        citations = []
        if request.mode == "chat":
            try:
                text = await llm_client.call_llm_json(request.user_input, CHAT_SYSTEM_PROMPT)
            except Exception as exc:
                raise UpstreamError("模型服务调用失败，请稍后重试") from exc
        else:
            service = getattr(http_request.app.state, "rag_chat", None)
            if service is None:
                raise ServiceUnavailable("知识库服务尚未就绪，请检查配置和数据库连接")
            result = await service.answer(request.user_input, top_k=request.top_k,
                                          min_score=request.min_score, document_ids=request.document_ids)
            text, citations = result.text, result.citations
        return ChatResponse(sucess=True, code=200, message="ok", data=text,
                            timestamp=timestamp, mode=request.mode, citations=citations)
    except ConversationError as exc:
        status, message = exc.status, exc.message
    except sqlite3.Error:
        status, message = 503, '会话存储暂不可用'
    except (ServiceUnavailable, UpstreamError) as exc:
        status = 503 if isinstance(exc, ServiceUnavailable) else 502
        message = str(exc)
        logger.error("聊天请求失败：%s", type(exc).__name__)
    except Exception as exc:
        status, message = 500, "服务内部错误，请稍后重试"
        logger.error("聊天请求异常：%s", type(exc).__name__)
    response.status_code = status
    return ChatResponse(sucess=False, code=status, message=message, data="",
                        timestamp=timestamp, mode=request.mode,
                        conversation_id=request.conversation_id, request_id=request.request_id)
