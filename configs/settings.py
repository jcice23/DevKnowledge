"""
系统全局配置文件
"""
import os
import logging
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class Settings:
    """
    agent全局配置，所有字段均通过环境变量覆盖
    """
    upload_dir: Path = Path(os.getenv(
        "UPLOAD_DIR", str(Path(__file__).resolve().parents[1] / "data" / "uploads")
    ))
    upload_max_bytes: int = int(os.getenv("UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))
    document_registry_path: Path = PROJECT_ROOT / os.getenv("DOCUMENT_REGISTRY_PATH", "data/documents.sqlite3")
    chat_database_path: Path = PROJECT_ROOT / os.getenv("CHAT_DATABASE_PATH", "data/conversations.sqlite3")
    chat_recent_turns: int = int(os.getenv("CHAT_RECENT_TURNS", "6"))
    chat_history_chars: int = int(os.getenv("CHAT_HISTORY_CHARS", "16000"))
    chat_summary_chars: int = int(os.getenv("CHAT_SUMMARY_CHARS", "4000"))
    chat_summary_input_chars: int = int(os.getenv("CHAT_SUMMARY_INPUT_CHARS", "16000"))
    chat_question_chars: int = int(os.getenv("CHAT_QUESTION_CHARS", "8000"))
    chat_request_timeout: float = float(os.getenv("CHAT_REQUEST_TIMEOUT", "150"))
    chat_lease_seconds: float = float(os.getenv("CHAT_LEASE_SECONDS", "180"))

    # 模型注册表与主节点配置
    llm_api_base_url: str = os.getenv("LLM_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")

    # Embedding 服务配置
    embed_api_base_url: str = os.getenv("EMBED_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    embed_api_key: str = os.getenv("EMBED_API_KEY", "")
    embed_model: str = os.getenv("EMBED_MODEL", "text-embedding-v3")

    # Milvus 数据库配置
    milvus_uri: str = os.getenv("MILVUS_URI", "")
    milvus_token: str = os.getenv("MILVUS_TOKEN", "")
    milvus_db_name: str = os.getenv("MILVUS_DB_NAME", "default")
    milvus_timeout: float = float(os.getenv("MILVUS_TIMEOUT", "30"))
    milvus_collection: str = os.getenv("MILVUS_COLLECTION", "document_chunks")
    rag_ingestion_report: Path = PROJECT_ROOT / os.getenv(
        "RAG_INGESTION_REPORT", "output/ingestion_report.json"
    )
    rag_max_context_chars: int = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "12000"))

# 全局单例
settings = Settings()
