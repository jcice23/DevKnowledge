"""会话请求领取 → 上下文 → 回答 → 原子提交；所有持久化操作在线程池执行。"""
import asyncio
from datetime import datetime, timezone, timedelta

from src.database.conversations import ConversationError
from src.prompts.chat_system_prompt import CHAT_SYSTEM_PROMPT
from src.workflow.conversation_context import ContextBuilder, ConversationContext
from src.workflow.rag_chat import ServiceUnavailable, UpstreamError


class ConversationChat:
    def __init__(self, store, llm, settings):
        if not 0 < settings.chat_request_timeout < settings.chat_lease_seconds:
            raise ValueError('聊天任务租约必须大于总超时')
        self.store, self.llm, self.settings = store, llm, settings
        self.builder = ContextBuilder(settings)

    async def answer(self, cid, rid, payload, rag):
        snapshot = await asyncio.to_thread(self.store.claim, cid, rid, payload, self.settings.chat_lease_seconds)
        if 'cached' in snapshot:
            return snapshot['cached']
        token = snapshot['token']
        try:
            async with asyncio.timeout(self.settings.chat_request_timeout):
                if payload['mode'] == 'rag' and rag is None:
                    raise ServiceUnavailable('知识库服务尚未就绪，请检查配置和数据库连接')
                versions = None
                if payload['mode'] == 'rag':
                    versions = await rag.ready_versions()
                if payload['mode'] == 'rag' and (not versions or payload['document_ids'] == []):
                    context = ConversationContext(snapshot['summary'], snapshot['summary_seq'], [], 0)
                else:
                    context = await self.builder.build(snapshot, self.llm)
                query, citations = None, []
                if payload['mode'] == 'chat':
                    try:
                        text = await self.llm.call_messages([
                            {'role': 'system', 'content': CHAT_SYSTEM_PROMPT}, *context.history(),
                            {'role': 'user', 'content': payload['user_input']},
                        ])
                    except Exception as exc:
                        raise UpstreamError('模型服务调用失败，请稍后重试') from exc
                else:
                    result = await rag.answer(payload['user_input'], top_k=payload['top_k'],
                        min_score=payload['min_score'], document_ids=payload['document_ids'], history=context.history(), versions=versions)
                    text, citations, query = result.text, result.citations, result.retrieval_query
                if not text.strip():
                    raise UpstreamError('模型返回空回答')
                response = dict(sucess=True, code=200, message='ok', data=text, citations=citations,
                    timestamp=datetime.now(timezone(timedelta(hours=8))).isoformat(), mode=payload['mode'],
                    conversation_id=cid, request_id=rid, history_turns=context.history_turns,
                    used_summary=bool(context.summary))
            # 提交事务在超时上下文外完成，避免返回失败后事务实际成功的歧义。
            await asyncio.to_thread(self.store.complete, cid, rid, token, response,
                                    context.summary, context.summary_seq, query)
            return response
        except BaseException as exc:
            if isinstance(exc, TimeoutError):
                error = UpstreamError('本轮处理超时，请重试')
            elif isinstance(exc, (ServiceUnavailable, UpstreamError, ConversationError)):
                error = exc
            else:
                error = UpstreamError('本轮处理失败，请重试')
            await asyncio.shield(asyncio.to_thread(self.store.fail, cid, rid, token, str(error)))
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise error from exc
