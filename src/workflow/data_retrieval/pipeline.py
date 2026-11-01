"""在线检索只读取已完成的入库版本，不创建集合、不生成回答。"""

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from pymilvus import DataType

from src.database.database_clinet import DataBaseClient
from src.llm.llm_client import MultiLLMClient
from src.workflow.data_storage.embedding import EmbeddingClient


@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: str
    document_id: str
    ingestion_id: str
    filename: str
    chunk_index: int
    text: str
    score: float
    metadata: dict


def _validate_ids(ids: list[str], name: str) -> None:
    if not isinstance(ids, list) or any(not isinstance(i, str) or not i.strip() for i in ids):
        raise ValueError(f"{name} 必须是非空字符串组成的列表（允许空列表）")


def load_ingestion_ids(report_path: str | Path, collection_name: str) -> list[str]:
    """从指定集合的正式入库报告 successes 中取版本，不接受 dry-run 报告。

    报告只是调用方选定的版本清单，不自动判断历史版本是否应被淘汰。
    """
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    if report.get("mode") != "ingest":
        raise ValueError("请使用正式入库报告，dry-run 不能证明入库成功")
    ids = [item["ingestion_id"] for item in report["successes"]
           if item["collection_name"] == collection_name]
    _validate_ids(ids, "ingestion_ids")
    return list(dict.fromkeys(ids))


class Retriever:
    """复用应用已有客户端；连接的创建和关闭均由调用方负责。"""

    def __init__(self, database: DataBaseClient, llm_client: MultiLLMClient,
                 collection_name: str | None = None):
        self.database = database
        self.embedder = EmbeddingClient(llm_client=llm_client)
        self.collection_name = (collection_name if collection_name is not None
                                else os.getenv("MILVUS_COLLECTION", "document_chunks"))
        if not self.collection_name.strip():
            raise ValueError("collection_name 不能为空")

    async def retrieve(
        self, query: str, *, ingestion_ids: list[str], top_k: int = 4,
        min_score: float = 0.2, document_ids: list[str] | None = None,
    ) -> list[RetrievalHit]:
        """返回最多 top_k 条结果，按 COSINE 分数降序排列。

        分数是余弦相似度，不是答案正确率；阈值需按实际语料调整。
        ingestion_ids 必须来自成功入库结果。空版本列表或空文档列表直接返回空。
        document_ids=None 表示不额外限制文档范围。
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("检索问题不能为空")
        if type(top_k) is not int or not 1 <= top_k <= 100:
            raise ValueError("top_k 必须是 1 到 100 的整数")
        if (isinstance(min_score, bool) or not isinstance(min_score, (int, float))
                or not math.isfinite(min_score) or not -1 <= min_score <= 1):
            raise ValueError("min_score 必须在 [-1, 1] 内")
        _validate_ids(ingestion_ids, "ingestion_ids")
        if document_ids is not None:
            _validate_ids(document_ids, "document_ids")
        if not ingestion_ids or document_ids == []:
            return []

        # 1. 先核对模型身份，再调用 Embedding，避免跨模型空间检索。
        schema = await self.database.describe_collection(self.collection_name)
        if schema.get("description") != f"DevKnowledge:v1:embedding={self.embedder.embedding_id}":
            raise ValueError("检索 Embedding 配置与入库模型不一致")
        vector_field = next((f for f in schema["fields"] if f["name"] == "embedding"), {})
        if vector_field.get("type") != DataType.FLOAT_VECTOR:
            raise ValueError("集合缺少 FLOAT_VECTOR 类型的 embedding 字段")

        # 2. 使用与入库相同的 LLM 客户端、配置和归一化方式生成问题向量。
        vector = (await self.embedder.embed_documents([query.strip()]))[0]
        if len(vector) != int(vector_field.get("params", {}).get("dim", 0)):
            raise ValueError("问题向量维度与入库向量维度不一致")

        # 3. 在数据库端先限制版本和文档，再做 top-k。参数绑定避免拼接用户输入。
        expression = "ingestion_id in {versions}"
        parameters = {"versions": list(dict.fromkeys(ingestion_ids))}
        if document_ids is not None:
            expression += " and document_id in {documents}"
            parameters["documents"] = list(dict.fromkeys(document_ids))
        await self.database.load_collection(self.collection_name)
        results = await self.database.search(
            self.collection_name, [vector], limit=top_k, anns_field="embedding",
            search_params={"metric_type": "COSINE"},
            filter=expression, filter_params=parameters,
            output_fields=["chunk_id", "document_id", "ingestion_id", "filename",
                           "chunk_index", "text", "metadata"],
            consistency_level="Strong",
        )

        # 4. COSINE 越大越相似。过滤低分并去掉重复主键，不丢弃来源元数据。
        hits, seen = [], set()
        for item in results[0] if results else []:
            score = float(item["distance"])
            row = item["entity"]
            chunk_id = row["chunk_id"]
            if not math.isfinite(score) or score < min_score or chunk_id in seen:
                continue
            seen.add(chunk_id)
            hits.append(RetrievalHit(
                chunk_id=chunk_id, document_id=row["document_id"], ingestion_id=row["ingestion_id"],
                filename=row["filename"], chunk_index=row["chunk_index"], text=row["text"],
                score=score, metadata=row["metadata"],
            ))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]
