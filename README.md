# DevKnowledge：个人 AI 助手

## 浏览器前端

`front/` 提供温暖简约风格的 JC 聊天页面，接入现有聊天与上传接口。
先按下文启动 FastAPI，再另开终端运行：

```powershell
cd front
npm install
npm run dev
```

访问 [JC 个人助手](http://localhost:5173)，详见 [前端说明](front/README.md)。

Python + FastAPI 后端，使用 OpenAI 兼容模型服务和 Milvus。
支持普通聊天、文档上传、离线入库和带来源引用的 RAG 问答；配有浏览器前端，支持服务器多轮会话、历史摘要与连续追问，暂无流式输出或跨会话长期记忆。

## 安装与配置

在项目根目录使用 Python 3.11+：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

创建或编辑 `.env`（不要提交密钥）：

```dotenv
LLM_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=你的聊天密钥
LLM_MODEL=你的账号实际可用的聊天模型
EMBED_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBED_API_KEY=你的向量密钥
EMBED_MODEL=text-embedding-v3
MILVUS_URI=http://localhost:19530
MILVUS_TOKEN=
MILVUS_DB_NAME=default
MILVUS_TIMEOUT=30
MILVUS_COLLECTION=document_chunks
RAG_INGESTION_REPORT=output/ingestion_report.json
RAG_MAX_CONTEXT_CHARS=12000
```

Milvus 需已启动，数据库需已存在；无鉴权时 token 留空。
`MILVUS_DB_NAME` 不要留空，使用默认库时填 `default`。
API 地址应包含服务商要求的 `/v1` 前缀；聊天与 Embedding 可使用不同服务。
配置完整不等于模型可用，模型名必须是该服务和账号支持的名称。
`RAG_INGESTION_REPORT` 相对路径以项目根目录为基准，亦支持绝对路径。
修改环境配置后重启服务。

## 多轮会话

会话保存在 `data/conversations.sqlite3`，局域网设备共用同一空间。普通聊天与知识库模式可延续同一话题；默认使用最近 6 轮及较早历史摘要，完整原文仍可查看。新建会话隔离上下文。

网页会自动创建和恢复服务器会话；旧浏览器记录通过“导入本机旧对话”手动迁移，不自动上传或清除。

API 调用先 `POST /conversations` 获取会话 ID，再向 `/chat` 同时传入 `conversation_id` 和本轮唯一的 `request_id`。旧调用不传这两个字段时仍是单轮。重复请求与失败重试使用原 ID 和原参数，避免重复保存回答。

配置、接口、故障恢复和联调说明见 [多轮上下文](docs/conversations.md)。更新代码后需要重启后端。

## 文档入库

支持 Markdown、UTF-8 TXT、DOCX、带文本层的 PDF；扫描 PDF 需先做 OCR。

```powershell
# 本地解析、清洗和分块，不连接模型或数据库
.\.venv\Scripts\python.exe -m src.workflow.data_storage "data/正则表达式.md" --dry-run --report output/dry_run.json

# 正式入库，会调用 Embedding 服务并写入 Milvus
.\.venv\Scripts\python.exe -m src.workflow.data_storage "data/正则表达式.md"

# 批量入库；若使用此报告做问答，将 RAG_INGESTION_REPORT 指向该文件
.\.venv\Scripts\python.exe -m src.workflow.data_storage data --recursive --report output/batch_report.json
```

不存在的集合按公共 Schema 和实际向量维度创建，使用 AUTOINDEX/COSINE 索引。
重复导入同一版本使用稳定主键 upsert；内容或分块变化产生新版本，旧版本保留。
多批写入不是事务，失败可能残留部分分块。离线导入的问答只使用正式报告 `successes` 中
当前集合的版本，报告不自动合并历史批次，也不自动选择每份文档的最新版本。
保留要使用的正式报告，不要用 dry-run 覆盖它。每次 RAG 请求重新读取报告，无需为新报告重启。
详细规则见 [入库说明](src/workflow/data_storage/README.md)。

## 启动与调用

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

打开 [接口文档](http://127.0.0.1:8000/docs)。目前提供 `POST /chat` 和 `POST /upload`。

### 知识库问答（默认）

```powershell
$body = @{ user_input = '正则表达式中的 \d 表示什么？'; top_k = 4; min_score = 0.2 } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/chat -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

请求字段：

| 字段 | 含义 |
| --- | --- |
| `user_input` | 必填，非空问题 |
| `mode` | `rag`（默认）或 `chat` |
| `top_k` | 召回数，默认 4，范围 1–100 |
| `min_score` | COSINE 阈值，默认 0.2，范围 -1–1；不是答案正确率 |
| `document_ids` | 可选文档范围；省略查全部启用文档，空列表不检索 |
| `user_location` | 保留原字段，目前不参与问答 |

请求不接受 `ingestion_ids`；启用版本由服务器文档状态和离线入库报告共同控制。
先过滤版本与文档，再向量检索、过滤低分、按字符预算组装完整片段，最后调用模型。
无参考材料时直接返回“当前知识库中没有足够的信息回答这个问题。”，不调用聊天模型。
模型也可在资料不足时返回该固定答复，不自动转为普通聊天。

响应示意：

```json
{
  "sucess": true,
  "code": 200,
  "message": "ok",
  "data": "回答正文。[1]",
  "timestamp": "2026-10-20T12:00:00+08:00",
  "mode": "rag",
  "citations": [{
    "number": 1,
    "chunk_id": "分块ID",
    "document_id": "文档ID",
    "ingestion_id": "成功入库版本ID",
    "filename": "资料.md",
    "chunk_index": 0,
    "text": "实际引用的原文",
    "score": 0.8,
    "metadata": {"start_index": 0, "end_index": 8, "offset_basis": "cleaned_unit"}
  }]
}
```

`sucess` 保留旧拼写，`data` 继续是答案字符串。只返回实际引用的来源，不改变原引用编号。
PDF 元数据中包含页码（若已提取），字符位置相对于清洗后的正文单元。
实质回答缺少引用或编号越界返回 502；编号检查不保证推断或事实本身正确。

### 普通聊天

显式传入 `mode="chat"`，不读取入库报告、不访问知识库，返回空引用列表：

```json
{"user_input": "你好", "mode": "chat"}
```

### 上传

```powershell
curl.exe -X POST http://127.0.0.1:8000/upload -F "file=@data/正则表达式.md"
```

上传成功后自动排队入库，无需执行离线命令。前端“文档上传”面板每两秒刷新状态，并支持重试失败文档。

- 原始文档：项目内 `data/uploads/`，不会将原始文件存入数据库。
- 文档元数据和任务状态：`data/documents.sqlite3`（SQLite，Python 自带，无需额外服务）。可用 `DOCUMENT_REGISTRY_PATH` 指定路径。
- 分块、向量和引用元数据：继续存入 Milvus；只有全部分块成功后才启用该版本。
- `GET /documents` 获取当前集合的网页上传文档；`GET /documents/{id}` 查看详情；`POST /documents/{id}/retry` 重试失败任务。
- 状态：`queued → processing → ready / failed`。正常退出会重新排队，进程异常终止后租约最多约 90 秒到期并恢复。后端运行时才会处理队列。
- 同名文件允许重复上传，视为不同文档；暂不提供删除或覆盖版本功能。已有 CLI 文档仍从原正式报告读取，不出现在网页上传列表。

更新后需重启后端。详见 [上传与状态管理](docs/upload.md)。

真实联调（会保存一份测试文档、调用模型并写入 Milvus）：

```powershell
.\.venv\Scripts\python.exe -m scripts.check_live_upload
# 使用已有联调文档重测，失败时重试，避免重复上传
.\.venv\Scripts\python.exe -m scripts.check_live_upload --document-id <文档ID>
```

结果保存在 `output/live_upload_report.json`。

## 状态与异常

| HTTP 状态 | 含义 |
| --- | --- |
| 200 | 回答成功或明确说明资料不足 |
| 422 | 问题为空、参数非法或包含未定义字段 |
| 503 | RAG 未初始化、配置或正式入库报告不可用 |
| 502 | 检索/模型调用失败、模型配置与集合不匹配或引用无效 |
| 500 | 未预期的内部异常 |

聊天异常响应保留原响应结构，`code` 与 HTTP 状态一致，`data` 为空，不返回第三方错误正文。
LLM 初始化失败会阻止启动；数据库初始化失败时普通聊天仍可使用，RAG 返回 503。
客户端创建成功不代表服务可达；实际请求中的连通性错误返回 502。
日志不主动记录正文或密钥，默认 INFO 级别。

## 验证

```powershell
# 模拟模型/数据库的自动化测试，不调用真实服务
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 显式真实联调：读取已有集合、调用模型，不入库、不删除数据
.\.venv\Scripts\python.exe -m scripts.check_live_chat
```

真实联调脚本使用当前正则表达式文档，核对模型身份、维度和成功版本分块数量，
通过应用生命周期调用 `/chat`，测试知识库引用、无资料和普通聊天；
报告写入 `output/live_chat_report.json`，可能包含答案和原文引用，应留在本地。

核心代码：`main.py` 管理生命周期，`src/workflow/rag_chat.py` 编排问答，
`src/workflow/data_retrieval/` 检索与组装资料，`src/workflow/data_storage/` 离线入库。
