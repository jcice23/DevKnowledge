"""复用数据库客户端和文档 Schema，校验集合后分批 upsert。"""

from pymilvus import MilvusClient

from src.schema.document_milvus import create_document_schema
from .config import StorageConfig


class MilvusDocumentStore:
    def __init__(self, database, config: StorageConfig):
        self.database = database
        self.config = config

    async def ensure_collection(self, dimension: int, embedding_id: str) -> None:
        schema = create_document_schema(dimension, embedding_id)
        name = self.config.collection_name
        if not await self.database.has_collection(name):
            indexes = MilvusClient.prepare_index_params()
            indexes.add_index(field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE")
            await self.database.create_collection(
                name, schema=schema, index_params=indexes, consistency_level="Strong",
            )
        actual = await self.database.describe_collection(name)
        if actual.get("description") != schema.description or actual.get("auto_id"):
            raise ValueError("已有集合的模型身份或主键配置不兼容，请使用新 collection")
        fields = {field["name"]: field for field in actual["fields"]}
        expected = schema.to_dict()["fields"]
        if set(fields) != {f["name"] for f in expected}:
            raise ValueError("已有集合的字段与文档 Schema 不一致")
        for field in expected:
            current = fields[field["name"]]
            if current.get("type") != field["type"]:
                raise ValueError(f"已有集合字段类型不兼容：{field['name']}")
            if bool(current.get("is_primary")) != bool(field.get("is_primary")):
                raise ValueError("已有集合主键不兼容")
            params = current.get("params", {})
            for key, value in field.get("params", {}).items():
                actual_value = int(params.get(key, 0))
                if (key == "max_length" and actual_value < int(value)
                        or key == "dim" and actual_value != int(value)):
                    raise ValueError(f"已有集合字段长度或维度不兼容：{field['name']}")

    async def upsert(self, records: list[dict]) -> int:
        written = 0
        for start in range(0, len(records), self.config.insert_batch_size):
            batch = records[start:start + self.config.insert_batch_size]
            try:
                result = await self.database.upsert(self.config.collection_name, batch)
                if result.get("upsert_count") != len(batch):
                    raise RuntimeError("Milvus 确认的写入数量不匹配")
            except Exception as exc:
                raise RuntimeError(
                    f"入库未完成，已确认 {written}/{len(records)} 个分块；"
                    "可能存在部分写入，可使用相同文件和配置重试"
                ) from exc
            written += len(batch)
        return written
