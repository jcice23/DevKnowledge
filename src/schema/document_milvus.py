"""RAG 文档分块的 Milvus Schema，一条记录对应一个分块。

字段与 workflow.data_storage.pipeline 生成的入库记录保持一致。
这里只构造 Schema，不连接数据库，也不创建 Collection 或索引。
参考：https://milvus.io/docs/zh/v2.5.x/schema.md
"""

from pymilvus import CollectionSchema, DataType, FieldSchema


def create_document_schema(dimension: int, embedding_id: str) -> CollectionSchema:
    """根据实际向量维度和模型身份构造 Schema。

    dimension 应取最终分块向量的长度；embedding_id 使用入库 Embedder
    的 embedding_id（由服务地址和模型名生成，不包含密钥）。
    Collection 描述沿用现有入库流程的格式，用于检查向量空间兼容性。

    VARCHAR 的 max_length 按 UTF-8 字节计算，不是中文字符数。
    主键由业务生成，关闭 auto_id，以支持相同分块的幂等 upsert。
    """
    if type(dimension) is not int or not 2 <= dimension <= 32768:
        raise ValueError("向量维度必须是 2 到 32768 之间的整数")
    if not isinstance(embedding_id, str) or not embedding_id.strip():
        raise ValueError("embedding_id 必须是非空字符串")

    document = [
        FieldSchema(
            name="chunk_id", dtype=DataType.VARCHAR, max_length=64,
            is_primary=True, auto_id=False,
            description="分块主键：由入库版本 ID 和分块序号生成的 SHA-256",
        ),
        FieldSchema(
            name="document_id", dtype=DataType.VARCHAR, max_length=256,
            description="所属文档 ID，用于限定检索范围或删除文档分块",
        ),
        FieldSchema(
            name="ingestion_id", dtype=DataType.VARCHAR, max_length=64,
            description="入库版本 ID，用于区分同一文档的不同内容或分块版本",
        ),
        FieldSchema(
            name="file_sha256", dtype=DataType.VARCHAR, max_length=64,
            description="原文件内容的 SHA-256 摘要",
        ),
        FieldSchema(
            name="filename", dtype=DataType.VARCHAR, max_length=1024,
            description="原始文件名，用于展示来源引用",
        ),
        FieldSchema(
            name="text", dtype=DataType.VARCHAR, max_length=65535,
            description="清洗后的分块正文，用于构造 RAG 上下文",
        ),
        FieldSchema(
            name="chunk_index", dtype=DataType.INT64,
            description="分块在本次入库版本中的顺序，从 0 开始",
        ),
        FieldSchema(
            name="metadata", dtype=DataType.JSON,
            description="来源元素、页码、字符区间、分块策略及向量模型身份",
        ),
        FieldSchema(
            name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dimension,
            description="最终分块正文的稠密向量，用于语义相似度检索",
        ),
    ]
    return CollectionSchema(
        fields=document,
        description=f"DevKnowledge:v1:embedding={embedding_id}",
        auto_id=False,
        enable_dynamic_field=False,
    )
