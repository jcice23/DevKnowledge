# 上传自动入库与文档状态

启动后端：`python -m uvicorn main:app --host 127.0.0.1 --port 8000`。
在 `front/` 运行 `npm run dev`，打开页面的“文档上传”面板即可使用。

## 存储

原始文档保存在项目 `data/uploads/`，文件名使用 UUID，同名上传不会覆盖。元数据和任务状态保存在 `data/documents.sqlite3`，数据库不保存原始文件。Milvus 保存解析后的分块、向量与引用元数据。这两处本地数据已加入 Git 忽略；备份时需同时保存上传目录、SQLite 状态文件与 Milvus。

可配置 `UPLOAD_DIR`、`UPLOAD_MAX_BYTES`（默认 50 MiB）、`DOCUMENT_REGISTRY_PATH`。相对的状态数据库路径以项目根目录为基准，上传目录建议使用绝对路径。Embedding 配置复用 LLM 客户端。

## 接口

| 接口 | 行为 |
| --- | --- |
| `POST /upload` | multipart `file`；保存并入队，返回 201、`success`、`message`、`data` |
| `GET /documents` | 当前集合的网页上传文档列表 `data`，以及 `worker_available` |
| `GET /documents/{document_id}` | 单个文档详情，未找到返回 404 |
| `POST /documents/{document_id}/retry` | 失败任务重新排队，返回 202；其他状态返回 409 |

`data` 包含 `document_id`、`original_filename`、`stored_filename`、`size_bytes`、`sha256`、`collection_name`、`status`、`error`、`ingestion_id`、`chunk_count`、`embedding_dimension`、Unix 秒时间戳 `created_at`/`updated_at`。入库成功前版本、分块数和维度为空。

```powershell
curl.exe -X POST http://127.0.0.1:8000/upload -F "file=@D:/documents/example.pdf"
curl.exe http://127.0.0.1:8000/documents
curl.exe -X POST http://127.0.0.1:8000/documents/文档ID/retry
```

支持 PDF、DOCX、MD、TXT。空文件 400，过大 413，不支持扩展名 415，缺少文件 422，文件保存失败 500，状态服务未就绪 503。扩展名通过不代表内容可解析；扫描版 PDF 暂无 OCR，可能入库失败。

## 任务与检索

`queued`（排队）→ `processing`（处理中）→ `ready`（可检索）或 `failed`（失败）。后台每个工作进程逐个处理；队列持久化到 SQLite，短事务领取任务并定期续租。正常关闭会重新排队，崩溃后租约约 90 秒到期，可自动恢复；后端需处于运行状态。

全部分块写入成功才发布有效版本。失败可能在 Milvus 留有部分分块，但不会被在线问答检索到。重试相同内容使用稳定分块主键进行 upsert。后台服务未初始化时上传仍可排队，修复配置并重启后继续处理；每份文件入库失败不会影响后续任务。

问答合并 SQLite 中当前集合的成功版本与现有正式 CLI 入库报告；没有报告时也能使用网页上传资料。现有报告损坏或为 dry-run 时仍返回服务未就绪，请修复报告。CLI 报告不覆盖上传状态，网页列表只展示网页上传资料。

暂不提供文档删除、原文件下载、重复内容去重或版本覆盖。多个服务实例必须共享同一上传目录和 SQLite 路径，建议个人使用时运行单个后端进程。
