"""文件 → 解析 → 清洗分块 → Embedding → Milvus，独立于 HTTP 服务。"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from src.database.database_clinet import get_database_client
from src.schema.document_milvus import create_document_schema
from .config import StorageConfig
from .data_load import load_document, SUPPORTED_EXTENSIONS
from .embedding import EmbeddingClient, normalize_vector
from .milvus_store import MilvusDocumentStore
from .splitter import split_documents


@dataclass(frozen=True)
class IngestionResult:
    document_id: str
    ingestion_id: str
    filename: str
    file_sha256: str
    collection_name: str
    chunk_count: int
    embedding_dimension: int


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def prepare_document(file_path: str | Path, config: StorageConfig) -> tuple[Path, str, list[dict]]:
    """本地预处理，不调用模型或数据库；也供 CLI --dry-run 使用。"""
    path = Path(file_path).expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("请选择 PDF、DOCX、MD、TXT 文件")
    if not 0 < path.stat().st_size <= config.max_file_bytes:
        raise ValueError("文件为空或超过大小限制")
    digest = file_hash(path)
    chunks = split_documents(load_document(path, config.max_document_chars), config)
    if file_hash(path) != digest:
        raise ValueError("文档在解析期间发生变化，请重试")
    return path, digest, chunks


async def ingest_document(
    file_path: str | Path, *, document_id: str | None = None,
    original_filename: str | None = None, config: StorageConfig | None = None,
    embedder=None, database=None,
) -> IngestionResult:
    """入库单个文件。注入的 database 由调用方关闭。

    相同文档、分块、模型身份生成稳定主键；变更后保留旧版本。
    全量解析和向量校验完成后才写入；Milvus 多批写入不具备文档级事务。
    只有成功返回的 ingestion_id 才应作为后续检索的已完成版本。
    """
    config = config or StorageConfig.from_env()
    path, digest, chunks = await asyncio.to_thread(prepare_document, file_path, config)
    document_id = digest if document_id is None else document_id
    filename = path.name if original_filename is None else original_filename
    for name, value, limit in (("document_id", document_id, 256), ("filename", filename, 1024)):
        if not isinstance(value, str) or not value.strip() or len(value.encode()) > limit:
            raise ValueError(f"{name} 不能为空或超过 {limit} 字节")
    embedder = embedder if embedder is not None else EmbeddingClient(batch_size=config.embedding_batch_size)
    vectors = [normalize_vector(v) for v in await embedder.embed_documents([c["text"] for c in chunks])]
    if len(vectors) != len(chunks) or len({len(v) for v in vectors}) != 1:
        raise ValueError("向量数量或维度与分块不匹配")
    schema = create_document_schema(len(vectors[0]), embedder.embedding_id)
    if await asyncio.to_thread(file_hash, path) != digest:
        raise ValueError("文档在向量化期间发生变化，请重试")
    identity = json.dumps(
        ["offline-v1", document_id, digest, filename, embedder.embedding_id, chunks],
        ensure_ascii=False, sort_keys=True, allow_nan=False,
    )
    ingestion_id = hashlib.sha256(identity.encode()).hexdigest()
    records = [{
        "chunk_id": hashlib.sha256(f"{ingestion_id}:{index}".encode()).hexdigest(),
        "document_id": document_id, "ingestion_id": ingestion_id,
        "file_sha256": digest, "filename": filename, "chunk_index": index,
        "text": chunk["text"], "embedding": vector,
        "metadata": {**chunk["metadata"], "embedding_model": embedder.model,
                     "embedding_id": embedder.embedding_id},
    } for index, (chunk, vector) in enumerate(zip(chunks, vectors))]
    # 从公共 Schema 读取字符串上限，避免两处定义漂移。
    limits = {f.name: f.params["max_length"] for f in schema.fields if "max_length" in f.params}
    for row in records:
        if any(len(row[name].encode()) > limit for name, limit in limits.items()):
            raise ValueError("入库字段超过 Schema 的 UTF-8 字节长度限制")
        if len(json.dumps(row["metadata"], ensure_ascii=False, allow_nan=False).encode()) > 65536:
            raise ValueError("分块元数据超过 JSON 字段限制")
    owns_database = database is None
    database = database if database is not None else get_database_client()
    try:
        store = MilvusDocumentStore(database, config)
        await store.ensure_collection(len(vectors[0]), embedder.embedding_id)
        count = await store.upsert(records)
    finally:
        if owns_database:
            await database.close()
    return IngestionResult(document_id, ingestion_id, filename, digest,
                           config.collection_name, count, len(vectors[0]))
