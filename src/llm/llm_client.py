
import asyncio
import logging
import math
import random
from dataclasses import dataclass

from openai import (
    AsyncOpenAI,
    APITimeoutError,
    APIConnectionError,
    RateLimitError,
    APIStatusError,
)

from configs.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMNodeConfig:
    base_url: str
    api_key: str
    model: str


def get_llm_config() -> LLMNodeConfig:
    return LLMNodeConfig(
        base_url=settings.llm_api_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )


def get_embedding_config() -> LLMNodeConfig:
    return LLMNodeConfig(
        base_url=settings.embed_api_base_url,
        api_key=settings.embed_api_key,
        model=settings.embed_model,
    )


class MultiLLMClient:

    def __init__(
        self,
        llm_config: LLMNodeConfig | None = None,
        embedding_config: LLMNodeConfig | None = None,
    ) -> None:

        self.llm_config = llm_config
        self.embedding_config = embedding_config

        self.llm_client = AsyncOpenAI(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            max_retries=0,
        ) if llm_config is not None else None

        self.embedding_client = (
            AsyncOpenAI(
                api_key=embedding_config.api_key,
                base_url=embedding_config.base_url,
                max_retries=0,
            )
            if embedding_config
            else None
        )

    @staticmethod
    def is_retryable(exc: Exception) -> bool:
        return (
            isinstance(
                exc,
                (
                    APITimeoutError,
                    asyncio.TimeoutError,
                    APIConnectionError,
                    RateLimitError,
                ),
            )
            or (
                isinstance(exc, APIStatusError)
                and exc.status_code >= 500
            )
        )

    async def call_llm_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_attempts: int = 3,
        max_tokens: int = 4096,
        timeout: float = 30.0,
    ) -> str:

        if max_attempts < 1:
            raise ValueError("max_attempts 必须 >= 1")
        if self.llm_client is None or self.llm_config is None:
            raise RuntimeError("聊天客户端未配置")

        messages = []

        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt,
            })

        messages.append({
            "role": "user",
            "content": prompt,
        })

        return await self.call_messages(messages, max_attempts=max_attempts, max_tokens=max_tokens, timeout=timeout)

    async def call_messages(self, messages: list[dict], *, max_attempts: int = 3,
                            max_tokens: int = 4096, timeout: float = 30.0) -> str:
        """接收由服务端编排的独立消息列表，不在客户端实例上保存会话状态。"""
        if max_attempts < 1:
            raise ValueError("max_attempts 必须 >= 1")
        if self.llm_client is None or self.llm_config is None:
            raise RuntimeError("聊天客户端未配置")
        if not messages or any(m.get('role') not in ('system', 'user', 'assistant')
                               or not isinstance(m.get('content'), str) for m in messages):
            raise ValueError('消息列表无效')
        messages = [dict(m) for m in messages]

        for attempt in range(max_attempts):
            try:
                completion = await self.llm_client.chat.completions.create(
                    model=self.llm_config.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )

                content = completion.choices[0].message.content

                if not content:
                    raise ValueError("模型返回空内容")

                return content

            except Exception as exc:
                if (
                    not self.is_retryable(exc)
                    or attempt == max_attempts - 1
                ):
                    logger.error("LLM 调用失败：%s", type(exc).__name__)
                    raise

                delay = min(
                    2 ** attempt + random.uniform(0, 0.5),
                    10.0,
                )

                logger.warning(
                    "LLM 调用失败，第 %s/%s 次尝试：%s",
                    attempt + 1,
                    max_attempts,
                    type(exc).__name__,
                )

                await asyncio.sleep(delay)

        raise RuntimeError("LLM 调用失败")

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]

    async def embed_documents(
        self, texts: list[str], *, batch_size: int = 10,
        max_attempts: int = 3, timeout: float = 60.0,
    ) -> list[list[float]]:
        """批量 Embedding；复用模型配置、连接与重试规则，返回原始向量。"""
        if (
            self.embedding_client is None
            or self.embedding_config is None
        ):
            raise RuntimeError("Embedding 客户端未配置")
        if type(batch_size) is not int or batch_size < 1 or type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("批大小和尝试次数必须是正整数")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必须是正有限数值")
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embedding 输入不能包含空文本")
        vectors = []
        dimension = None
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            for attempt in range(max_attempts):
                try:
                    response = await self.embedding_client.embeddings.create(
                        model=self.embedding_config.model, input=batch,
                        encoding_format="float", timeout=timeout,
                    )
                    break
                except Exception as exc:
                    if not self.is_retryable(exc) or attempt == max_attempts - 1:
                        raise RuntimeError(f"Embedding 调用失败：{type(exc).__name__}") from exc
                    await asyncio.sleep(min(2 ** attempt, 8))
            try:
                items = sorted(response.data, key=lambda item: item.index)
                indices = [item.index for item in items]
                if any(type(i) is not int for i in indices) or indices != list(range(len(batch))):
                    raise ValueError("向量数量或索引不匹配")
                for item in items:
                    vector = item.embedding
                    if not isinstance(vector, list) or not vector or any(
                        isinstance(x, bool) or not isinstance(x, (int, float)) for x in vector
                    ):
                        raise ValueError("无效向量")
                    norm = math.hypot(*vector)
                    if not math.isfinite(norm) or norm == 0:
                        raise ValueError("零向量或非有限数值")
                    dimension = dimension or len(vector)
                    if len(vector) != dimension:
                        raise ValueError("向量维度不一致")
                    vectors.append(vector)
            except (AttributeError, TypeError, ValueError):
                raise RuntimeError("Embedding 响应格式、数量或向量无效") from None
        return vectors

    async def close(self) -> None:
        try:
            if self.llm_client is not None:
                await self.llm_client.close()
        finally:
            if self.embedding_client is not None:
                await self.embedding_client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()


def get_llm_client() -> MultiLLMClient:
    """你好"""
    return MultiLLMClient(
        llm_config=get_llm_config(),
        embedding_config=get_embedding_config(),
    )

async def main():
    async with get_llm_client() as client:
        result = await client.call_llm_json(
            prompt="今天心情不好",
            system_prompt=(
                '你是一个人工智能助手，回答用户的问题'
            ),
        )
        print(result)


if __name__ == "__main__":
    # asyncio.run(main())
    print(get_llm_client.__doc__)
