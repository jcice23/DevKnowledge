"""FastAPI 入口与共享客户端生命周期。"""
from contextlib import AsyncExitStack, asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI

from configs.logging import init_default_logger
from configs.settings import settings
from src.api.chat import router as chat_router
from src.api.upload import router as upload_router
from src.database.database_clinet import get_database_client
from src.llm.llm_client import get_llm_client
from src.workflow.data_retrieval import Retriever
from src.workflow.rag_chat import RagChat
from src.database.document_registry import DocumentRegistry
from src.workflow.document_worker import DocumentWorker
from src.database.conversations import ConversationStore
from src.workflow.conversation_chat import ConversationChat
from src.api.conversations import router as conversations_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_default_logger()
    app.state.rag_chat = None
    app.state.document_registry = await asyncio.to_thread(DocumentRegistry, settings.document_registry_path)
    app.state.document_worker = None
    app.state.conversation_chat = None
    app.state.conversation_store = await asyncio.to_thread(ConversationStore, settings.chat_database_path)
    async with AsyncExitStack() as stack:
        # 配置缺失立即暴露；SDK 构造成功不代表已连通服务，调用时仍检查异常。
        if not all(v.strip() for v in (settings.llm_api_base_url, settings.llm_api_key, settings.llm_model)):
            raise ValueError("请配置 LLM_API_BASE_URL、LLM_API_KEY、LLM_MODEL")
        llm = get_llm_client()
        stack.push_async_callback(llm.close)
        app.state.llm_client = llm
        app.state.conversation_chat = ConversationChat(app.state.conversation_store, llm, settings)
        try:
            database = get_database_client()
            stack.push_async_callback(database.close)
            retriever = Retriever(database, llm, settings.milvus_collection)
            app.state.rag_chat = RagChat(
                retriever, llm, settings.rag_ingestion_report, settings.rag_max_context_chars,
                registry=app.state.document_registry,
            )
            worker = DocumentWorker(app.state.document_registry, settings.upload_dir,
                                    settings.milvus_collection, llm, database)
            worker.start()
            app.state.document_worker = worker
            stack.push_async_callback(worker.close)
        except Exception as exc:
            logger.error("RAG 初始化不可用：%s", type(exc).__name__)
        try:
            yield
        finally:
            app.state.rag_chat = None
            app.state.document_worker = None
            app.state.conversation_chat = None


app = FastAPI(title="个人助手聊天 API", version="1.0.0", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(upload_router)
app.include_router(conversations_router)
