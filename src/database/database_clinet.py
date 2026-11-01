"""异步 Milvus 客户端：配置、请求执行与连接生命周期。

在异步函数中创建，使用 async with 或 await close() 释放连接。
CRUD 方法放在 src.utils.milvus_crud，本层不额外重试写入请求。
"""

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Any

from pymilvus import AsyncMilvusClient

from configs.settings import settings
from src.utils.milvus_crud import MilvusCRUD

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MilvusConfig:
    milvus_uri: str = settings.milvus_uri
    milvus_token: str = field(default=settings.milvus_token, repr=False)
    milvus_db_name: str = settings.milvus_db_name
    milvus_timeout: float = settings.milvus_timeout

    def __post_init__(self):
        if not isinstance(self.milvus_uri, str) or not self.milvus_uri.strip():
            raise ValueError("请配置MILVUS_URI")
        # 未开启鉴权的本地服务允许 token 为空。
        if not isinstance(self.milvus_token, str):
            raise ValueError("MILVUS_TOKEN 必须是字符串")
        if not isinstance(self.milvus_db_name, str) or not self.milvus_db_name.strip():
            raise ValueError("MILVUS_DB_NAME 不能为空")
        validate_timeout(self.milvus_timeout)


def validate_timeout(timeout: float) -> None:
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("timeout 必须为大于 0 的有限数值")


def get_milvus_config() -> MilvusConfig:
    """ 获取Milvus连接配置 """
    return MilvusConfig(
        milvus_uri=settings.milvus_uri,
        milvus_token=settings.milvus_token,
        milvus_db_name=settings.milvus_db_name,
        milvus_timeout=settings.milvus_timeout,
    )


class DataBaseClient(MilvusCRUD):
    """一个应用生命周期内复用一个实例；关闭前应先等待业务请求结束。"""

    def __init__(self, milvus_config: MilvusConfig | None = None) -> None:
        self.milvus_config = milvus_config if milvus_config is not None else get_milvus_config()
        self.milvus_client = AsyncMilvusClient(
            uri=self.milvus_config.milvus_uri,
            token=self.milvus_config.milvus_token,
            db_name=self.milvus_config.milvus_db_name,
            timeout=self.milvus_config.milvus_timeout,
        )
        self._closed = False
        self._close_lock = asyncio.Lock()

    async def _call(self, operation: str, **kwargs: Any) -> Any:
        if self._closed:
            raise RuntimeError("数据库客户端已关闭")
        timeout = kwargs.get("timeout")
        if timeout is None:
            timeout = self.milvus_config.milvus_timeout
        validate_timeout(timeout)
        kwargs["timeout"] = timeout
        try:
            return await getattr(self.milvus_client, operation)(**kwargs)
        except Exception as exc:
            # 不记录凭据、正文、过滤表达式或 SDK 原始异常文本。
            logger.error("Milvus %s 失败：%s", operation, type(exc).__name__)
            raise

    async def close(self) -> None:
        """允许重复或并发关闭；关闭失败时保留再次关闭的机会。"""
        async with self._close_lock:
            if not self._closed:
                await self.milvus_client.close()
                self._closed = True

    async def __aenter__(self):
        if self._closed:
            raise RuntimeError("数据库客户端已关闭")
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()


def get_database_client() -> DataBaseClient:
    return DataBaseClient(get_milvus_config())
