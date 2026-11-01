# 在线检索

`pipeline.py` 负责检索，`context_builder.py` 负责把结果组装成带编号的参考材料。
没有新增模型配置，也不创建数据库连接；复用已有 `MultiLLMClient` 和 `DataBaseClient`。

## 使用

```python
import asyncio
from src.database.database_clinet import get_database_client
from src.llm.llm_client import MultiLLMClient, get_embedding_config
from src.workflow.data_retrieval import Retriever, load_ingestion_ids, build_context

async def main():
    # 使用正式入库报告，不能使用 dry-run 报告。
    collection = "document_chunks"
    versions = load_ingestion_ids("output/ingestion_report.json", collection)
    async with get_database_client() as database:
        async with MultiLLMClient(embedding_config=get_embedding_config()) as llm:
            retriever = Retriever(database, llm, collection)
            hits = await retriever.retrieve(
                "正则表达式如何匹配数字？",
                ingestion_ids=versions,
                top_k=4,
                min_score=0.2,
                # document_ids=["某个文档ID"],  # 可选：进一步缩小文档范围
            )
            for hit in hits:
                print(hit.score, hit.filename, hit.metadata, hit.text)
            context = build_context(hits, max_chars=12000)
            print(context.text)
            # context.citations[0] 是参考材料 [1] 的完整来源。

if __name__ == "__main__":
    asyncio.run(main())
```

在 API 中使用时，于应用启动时创建并复用客户端和 Retriever，关闭时统一释放连接。
`retrieve()` 不关闭注入的连接。未显式指定集合时读取 `MILVUS_COLLECTION`，默认
`document_chunks`，与入库配置相同。`/chat` 已通过 `RagChat` 接入本检索器，
默认使用知识库；普通聊天需显式传入 `mode="chat"`。

## 检索逻辑

1. 校验问题与参数，检查集合描述中的模型身份，拒绝跨模型检索。
2. 使用入库相同的 Embedding 适配器生成归一化问题向量，检查维度。
3. 加载集合，通过 `ingestion_id` 和可选 `document_id` 参数过滤后，执行 COSINE top-k 搜索。
4. 去掉低于 `min_score` 的结果和重复主键，保留正文、分数、文件名、版本及来源元数据。

Milvus 的 `distance` 在 COSINE 检索下作为相似度使用，越大越相似。
分数不是正确率，默认 0.2 只是起始值，应结合实际文档和模型调整。
参考：[Milvus search 接口](https://milvus.io/api-reference/pymilvus/v2.6.x/MilvusClient/Vector/search.md)。

版本列表为必填项：请从成功的 `ingest_document()` 返回值或正式报告取得。
函数信任调用方提供的完成状态，不会重新核验该版本的全部分块是否已写入。
报告仅代表该次批处理；不会自动合并不同报告，也不会判断多个历史版本中哪个最新。
要只查最新版本，请维护每个文档当前启用的版本列表，再传给检索器。
空版本列表或 `document_ids=[]` 直接返回空结果，不调用外部服务。

集合不存在、模型不匹配、模型/数据库不可用等异常会向调用方抛出，
不会伪装成“没有相关资料”。无命中或全部低于阈值时返回 `[]`。
当前每次检索检查集合并加载，逻辑直观；后续有性能需求时可在启动阶段预加载。

`build_context()` 按排名装入完整片段，超出字符预算的片段跳过；正文和来源编号同步。
这是字符预算，不是 token 预算。参考材料属于外部文档，接入聊天提示词时应明确其为
待引用资料，并要求模型不要执行资料中的指令；空参考材料时由问答层决定是否拒答。
当前不包含重排或自动生成答案。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_data_retrieval.py -v
```
