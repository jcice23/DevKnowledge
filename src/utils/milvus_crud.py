"""Milvus 集合及数据操作；通过客户端的 _call 统一执行异步请求。"""

from abc import ABC, abstractmethod
from typing import Any


class MilvusCRUD(ABC):
    """供 DataBaseClient 继承，CRUD 层不创建或关闭数据库连接。"""

    @abstractmethod
    async def _call(self, operation: str, **kwargs: Any) -> Any:
        """由客户端提供超时、日志及关闭状态检查。"""

    async def list_collections(self, **kwargs: Any) -> list[str]:
        return await self._call("list_collections", **kwargs)

    async def has_collection(self, collection_name: str, **kwargs: Any) -> bool:
        return await self._call("has_collection", collection_name=collection_name, **kwargs)

    async def describe_collection(self, collection_name: str, **kwargs: Any) -> dict:
        return await self._call("describe_collection", collection_name=collection_name, **kwargs)

    async def create_collection(
        self, collection_name: str, dimension: int | None = None, **kwargs: Any,
    ) -> None:
        """RAG 建表通过 schema/index_params 传入文档 Schema 和向量索引。"""
        await self._call(
            "create_collection", collection_name=collection_name, dimension=dimension, **kwargs,
        )

    async def create_index(self, collection_name: str, index_params: Any, **kwargs: Any) -> None:
        await self._call(
            "create_index", collection_name=collection_name, index_params=index_params, **kwargs,
        )

    async def load_collection(self, collection_name: str, **kwargs: Any) -> None:
        """将集合加载到内存，供搜索和查询使用。"""
        await self._call("load_collection", collection_name=collection_name, **kwargs)

    async def insert(self, collection_name: str, data: list[dict], **kwargs: Any) -> dict:
        if not data:
            raise ValueError("插入数据不能为空")
        return await self._call("insert", collection_name=collection_name, data=data, **kwargs)

    async def upsert(self, collection_name: str, data: list[dict], **kwargs: Any) -> dict:
        """按主键新增或替换完整记录；更新时传入包含向量的完整分块数据。"""
        if not data:
            raise ValueError("写入数据不能为空")
        return await self._call("upsert", collection_name=collection_name, data=data, **kwargs)

    async def search(
        self, collection_name: str, data: list[list[float]], *, limit: int = 10,
        filter: str = "", output_fields: list[str] | None = None, **kwargs: Any,
    ) -> list[list[dict]]:
        """向量检索；RAG 可传 anns_field='embedding'，每个查询向量返回一组命中。"""
        if not data:
            raise ValueError("查询向量不能为空")
        self._validate_limit(limit)
        return await self._call(
            "search", collection_name=collection_name, data=data, limit=limit,
            filter=filter, output_fields=output_fields, **kwargs,
        )

    async def query(
        self, collection_name: str, *, filter: str = "", limit: int = 100,
        output_fields: list[str] | None = None, **kwargs: Any,
    ) -> list[dict]:
        """标量查询，可通过 kwargs 传 ids 或 filter_params。"""
        self._validate_limit(limit)
        # Milvus 的 count(*) 聚合禁止分页，不能附带默认的 limit。
        if output_fields == ["count(*)"]:
            return await self._call(
                "query", collection_name=collection_name, filter=filter,
                output_fields=output_fields, **kwargs,
            )
        return await self._call(
            "query", collection_name=collection_name, filter=filter, limit=limit,
            output_fields=output_fields, **kwargs,
        )

    async def delete(
        self, collection_name: str, *, ids: list[int] | list[str] | None = None,
        filter: str = "", **kwargs: Any,
    ) -> dict:
        """按主键或过滤条件删除；必须提供其中一种，禁止无条件删除。"""
        if ids is not None:
            if not ids or filter.strip():
                raise ValueError("请提供非空 ids，且不能同时指定 filter")
        elif not filter.strip():
            raise ValueError("删除操作必须指定 ids 或 filter")
        return await self._call(
            "delete", collection_name=collection_name, ids=ids, filter=filter, **kwargs,
        )

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit 必须为正整数")
