"""离线入库参数；连接与模型配置复用 configs.settings。"""

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class StorageConfig:
    collection_name: str = "document_chunks"
    chunk_size: int = 800
    chunk_overlap: int = 120
    embedding_batch_size: int = 10
    insert_batch_size: int = 100
    max_file_bytes: int = 50 * 1024 * 1024
    max_document_chars: int = 5_000_000
    max_chunks: int = 20000

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,254}", self.collection_name):
            raise ValueError("collection 名称只能包含字母、数字和下划线，且不能以数字开头")
        for name in ("chunk_size", "embedding_batch_size", "insert_batch_size",
                     "max_file_bytes", "max_document_chars", "max_chunks"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} 必须是正整数")
        if self.chunk_size > 12000:
            raise ValueError("chunk_size 不能超过 12000 字符")
        if type(self.chunk_overlap) is not int or not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("要求 0 <= chunk_overlap < chunk_size")

    @classmethod
    def from_env(cls):
        return cls(
            collection_name=os.getenv("MILVUS_COLLECTION", "document_chunks"),
            chunk_size=int(os.getenv("STORAGE_CHUNK_SIZE", "800")),
            chunk_overlap=int(os.getenv("STORAGE_CHUNK_OVERLAP", "120")),
            embedding_batch_size=int(os.getenv("STORAGE_EMBEDDING_BATCH_SIZE", "10")),
            insert_batch_size=int(os.getenv("MILVUS_INSERT_BATCH_SIZE", "100")),
        )
