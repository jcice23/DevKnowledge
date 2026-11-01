"""共享个人空间的会话接口；同步路由由 FastAPI 在线程池执行。"""
import sqlite3
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.chat import Citation
from src.database.conversations import ConversationError

router = APIRouter(prefix='/conversations', tags=['会话'])


def call(request, method, *args):
    store = getattr(request.app.state, 'conversation_store', None)
    if store is None:
        raise HTTPException(503, '会话服务尚未就绪')
    try:
        return getattr(store, method)(*args)
    except ConversationError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    except sqlite3.Error as exc:
        raise HTTPException(503, '会话存储暂不可用') from exc


class ImportedMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str | None = None
    role: Literal['user', 'assistant']
    text: str = Field(min_length=1, max_length=100000)
    mode: Literal['chat', 'rag']
    citations: list[Citation] = Field(default_factory=list, max_length=100)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    messages: list[ImportedMessage] = Field(min_length=1, max_length=2000)


@router.post('', status_code=201)
def create(request: Request):
    return {'data': call(request, 'create')}


@router.get('')
def list_conversations(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return call(request, 'list', limit, offset)


@router.post('/import')
def import_conversation(body: ImportRequest, request: Request):
    return {'data': call(request, 'import_history', body.source_id, body.title,
                         [m.model_dump() for m in body.messages])}


@router.get('/{conversation_id}')
def history(conversation_id: str, request: Request, limit: int = Query(50, ge=1, le=100),
            before: int | None = Query(None, ge=1)):
    return call(request, 'history', conversation_id, limit, before)


@router.get('/{conversation_id}/requests/{request_id}')
def request_status(conversation_id: str, request_id: str, request: Request):
    return {'data': call(request, 'request_status', conversation_id, request_id)}


@router.delete('/{conversation_id}', status_code=204)
def delete(conversation_id: str, request: Request):
    call(request, 'delete', conversation_id)
