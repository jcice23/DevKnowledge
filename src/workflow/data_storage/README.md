# RAG 离线入库

这里的“离线”指独立批处理，不依赖聊天或上传 HTTP 接口。
正式入库仍会把分块正文发送到配置的 Embedding 服务，并连接 Milvus。
`--dry-run` 仅在本地解析、清洗和分块，不调用这些服务。

## 配置

安装项目 requirements.txt 中的依赖，在项目根目录 `.env` 中配置：

```dotenv
EMBED_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBED_API_KEY=你的密钥
EMBED_MODEL=text-embedding-v3
MILVUS_URI=http://localhost:19530
MILVUS_TOKEN=
MILVUS_DB_NAME=default
MILVUS_TIMEOUT=60
MILVUS_COLLECTION=document_chunks
STORAGE_CHUNK_SIZE=800
STORAGE_CHUNK_OVERLAP=120
STORAGE_EMBEDDING_BATCH_SIZE=10
MILVUS_INSERT_BATCH_SIZE=100
```

Embedding 配置直接复用 `src.llm.llm_client.get_embedding_config()`，
批量调用使用 `MultiLLMClient.embed_documents()`，入库层不单独维护 HTTP 请求。
不需要配置聊天模型。数据库需事先存在；集合不存在时会按实际向量维度
使用 `src/schema/document_milvus.py` 创建 Schema 和 AUTOINDEX/COSINE 索引。
已有集合必须具有相容的模型身份、字段类型、主键和向量维度，否则停止写入。

## 命令行

在项目根目录运行：

```powershell
# 先检查本地解析和分块
.\.venv\Scripts\python.exe -m src.workflow.data_storage "data/正则表达式.md" --dry-run

# 正式导入单文件
.\.venv\Scripts\python.exe -m src.workflow.data_storage "data/正则表达式.md"

# 递归导入目录，逐文件处理，失败后继续下一份
.\.venv\Scripts\python.exe -m src.workflow.data_storage data --recursive --report output/batch_report.json
```

可用 `--collection` 指定集合，单文件可用 `--document-id` 指定业务 ID。
默认文档 ID 为文件内容 SHA-256。目录默认只扫描当前层，忽略不支持的扩展名；
递归模式不进入隐藏目录，不跟随符号链接目录。
报告默认写入 `output/ingestion_report.json`，覆盖上次报告；请为需保留的批次指定独立路径。
存在失败文件时退出码为 1；路径或参数错误为 2。

## Python 调用

```python
import asyncio
from src.workflow.data_storage.pipeline import ingest_document

async def main():
    result = await ingest_document(
        "data/uploads/实际保存的文件名.pdf",
        document_id="上传接口返回的文档ID",
        original_filename="员工手册.pdf",
    )
    print(result.ingestion_id, result.chunk_count)

if __name__ == "__main__":
    asyncio.run(main())
```

通过 `database=` 可传入现有 `DataBaseClient`，调用方负责关闭该连接。
未注入时，函数自行创建并关闭连接。参数 `config=StorageConfig(...)` 可调整
分块、批大小、文件大小、字符数和分块数量上限。

已有 LLM 客户端时，可通过
`embedder=EmbeddingClient(llm_client=llm_client)` 注入入库函数
（从本目录 `embedding` 模块导入 `EmbeddingClient`）。
配置和连接均复用该实例，由调用方关闭；未注入时自动创建仅启用 Embedding
的 `MultiLLMClient`，请求完成或失败后自动关闭。

## 处理规则和边界

- PDF 使用 pypdf 提取文本层，保留原始页码；不做 OCR，不处理加密 PDF。
- DOCX 使用 python-docx，按正文顺序提取段落与表格；不提取图片、页眉页脚，
  不保证嵌套表格完整性；表格过长时也按字符分块。
- TXT 和 Markdown 使用 UTF-8（支持 BOM）；Markdown 保留原始标记。
- 清洗统一换行、Unicode NFC，去除控制字符、行尾空白和多余空行，保留缩进。
- 当前采用带重叠的字符分块，优先在句尾或换行处切分，不额外调用模型做语义分块。
  不跨正文单元合并，Word 的短段落可能形成较小分块。
- 每块保留清洗后正文单元的 `[start_index, end_index)` 区间，PDF 额外保留页码。
- 分块长度按字符而非 token 计算，应按服务商输入上限调整。
- 默认单文件最多 50 MiB、正文 500 万字符、2 万块。解析在工作线程执行，
  这些限制不构成解析器硬内存/时间隔离，适合个人可信文档；超大文档先拆分。

## 重复导入和失败

同一文档 ID、内容、文件名、分块结果和模型身份生成稳定的 `ingestion_id`
及 `chunk_id`，通过 upsert 重跑不会增加同版本的逻辑重复记录，但仍调用 Embedding。
内容或分块变化会产生新版本，旧版本保留，不隐式删除。

解析和全部向量校验完成后才开始写入。多批 Milvus 写入不是文档级事务，
失败或取消可能留下部分分块；相同输入和配置可重试补齐。
**只有成功返回或报告 successes 中的 ingestion_id 才是完整入库版本。**
后续检索应按已完成的版本过滤；目前没有自动维护 ready 状态的文档注册表。
若报告写入失败，应重新运行入库以获得成功报告。首次建集合及同文档入库请串行执行。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_data_storage.py -v
```

测试使用临时文档、真实 Schema 与模拟网络/数据库，不发送个人文档。
