"""入库向量适配：配置与请求复用 LLM 客户端，仅负责身份和归一化。"""

import hashlib
import json
import math

from src.llm.llm_client import MultiLLMClient, get_embedding_config


def normalize_vector(vector: list[float]) -> list[float]:
    if not isinstance(vector, list) or len(vector) < 2 or any(
        isinstance(x, bool) or not isinstance(x, (int, float)) for x in vector
    ):
        raise ValueError("Embedding 返回无效向量")
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Embedding 返回零向量或非有限数值")
    return [x / norm for x in vector]


class EmbeddingClient:
    def __init__(self, *, batch_size: int = 10, llm_client: MultiLLMClient | None = None):
        self.llm_client = llm_client
        self.config = llm_client.embedding_config if llm_client is not None else get_embedding_config()
        if self.config is None:
            raise ValueError("Embedding 客户端未配置")
        if not all(value.strip() for value in (self.config.base_url, self.config.model, self.config.api_key)):
            raise ValueError("请配置 EMBED_API_BASE_URL、EMBED_API_KEY、EMBED_MODEL")
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("embedding 批大小必须是正整数")
        self.batch_size = batch_size
        self.model = self.config.model.strip()
        # 保留之前的身份算法，已有集合不需要因客户端重构而重新入库。
        self.embedding_id = hashlib.sha256(
            json.dumps([self.config.base_url.strip().rstrip("/"), self.model], ensure_ascii=False).encode()
        ).hexdigest()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.llm_client is not None:
            vectors = await self.llm_client.embed_documents(texts, batch_size=self.batch_size)
        else:
            # 只初始化 LLM 客户端的 Embedding 部分，无需聊天配置；异常时也关闭连接。
            async with MultiLLMClient(embedding_config=self.config) as client:
                vectors = await client.embed_documents(texts, batch_size=self.batch_size)
        return [normalize_vector(vector) for vector in vectors]
