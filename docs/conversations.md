# 多轮会话与上下文

会话保存在服务器的 `data/conversations.sqlite3`，与文档状态数据库独立。当前是共享个人空间：访问同一后端的局域网设备共用会话列表，不区分账号。切换普通聊天与知识库模式继续同一话题，新建会话隔离历史。

## 接口

| 接口 | 行为 |
| --- | --- |
| `POST /conversations` | 创建空会话，201，返回 `data.id` |
| `GET /conversations?limit=50&offset=0` | 按更新时间倒序分页，返回 `data` 与 `next_offset` |
| `GET /conversations/{id}?limit=50&before=序号` | 最新一页轮次按时间正序返回；`next_before` 用于加载更早记录 |
| `GET /conversations/{id}/requests/{request_id}` | 读取请求状态、原请求参数及已完成响应 |
| `DELETE /conversations/{id}` | 删除会话、消息和摘要，204；处理中返回 409 |
| `POST /conversations/import` | 手动导入旧记录，按 `source_id` 去重 |

历史接口还返回 `conversation.summary`、摘要覆盖位置 `summary_seq`、`processing_request_id`。每轮包含 `request_id`、`seq`、`status`、`messages`、`request`、`response` 和 `retrieval_query`。时间戳使用 Unix 秒；列表与历史每页最多 100 项。

`POST /chat` 同时传入会话和请求标识即可启用多轮：

```json
{
  "conversation_id": "创建接口返回的会话 ID",
  "request_id": "客户端为本轮生成的唯一 ID",
  "user_input": "它和字母匹配有什么区别？",
  "mode": "rag"
}
```

响应保持 `sucess`、`code`、`message`、`data`、`timestamp`、`mode`、`citations`，新增 `conversation_id`、`request_id`、`history_turns`（原文历史轮数）、`used_summary`。不传两个 ID 时保持原单轮行为；只传一个返回 422。客户端不能传入系统消息、摘要或任意历史。

同一会话一次只处理一个请求，冲突返回 409；不同会话并行。同一请求 ID 和相同参数重复提交时，已完成请求返回原响应，失败请求重新执行。改变同一 ID 的问题、模式或参数返回 409。重试较早的失败问题时复用原记录并移至当前末尾，避免摘要覆盖顺序错乱。

失败响应不暴露服务商原始错误。无资料仍返回 200 和明确资料不足答复；摘要、改写或模型失败返回 502，存储或服务未就绪返回 503，已删除会话返回 404。

## 上下文与摘要

普通聊天使用服务器系统提示、历史摘要、最近完整问答、当前问题。只有完成的轮次进入上下文，失败与处理中轮次被排除；切换模式不会清空历史。

超过轮数或原文字符预算时，将最早的完整轮次逐步合并进摘要。单轮原文过大时分片归纳，单次历史数据输入受摘要输入预算约束，不截断持久化原记录。摘要只是历史数据，不是系统指令，也不是知识库证据。摘要与覆盖位置只有在本轮回答成功后才和回答原子提交。

摘要保留主题、用户约束、纠正与未解决问题，区分用户陈述和助手建议。摘要生成失败、为空或超限时本轮失败，原摘要保持不变。摘要可能遗漏信息；前端可查看只读摘要，也可分页阅读完整记录。

知识库先检查有效版本和文档范围，再用历史改写独立检索问题、重新检索并回答。旧编号和引用正文不进入历史上下文，引用始终对应本轮实际分块。当前请求的 `document_ids` 生效，不隐式继承或扩大范围；无资料不调用聊天模型。检索改写失败不降级为无历史查询。

## 配置与恢复

```dotenv
CHAT_DATABASE_PATH=data/conversations.sqlite3
CHAT_RECENT_TURNS=6
CHAT_HISTORY_CHARS=16000
CHAT_SUMMARY_CHARS=4000
CHAT_SUMMARY_INPUT_CHARS=16000
CHAT_QUESTION_CHARS=8000
CHAT_REQUEST_TIMEOUT=150
CHAT_LEASE_SECONDS=180
```

预算是字符数，不是模型 token 数；选择的模型需能容纳系统提示、摘要、历史、当前问题及 `RAG_MAX_CONTEXT_CHARS` 指定的资料。上下文预算应与模型容量一起调整。租约必须长于处理超时，摘要输入预算必须为旧摘要及新片段留出空间。

SQLite 初始化时自动创建表，无需新增数据库服务。修改配置需重启后端。进程异常退出时，遗留请求在 180 秒租约到期后的下一次状态查询或会话操作中标记失败，允许手动重试；领取标识防止过期任务覆盖新结果。正常取消请求会标记失败，不自动继续生成。

浏览器刷新后重新读取服务器历史；请求进行中每两秒查询状态。网络异常后先核对请求是否已经完成，再决定是否允许重试。界面只在 localStorage 保存草稿、选中会话、模式和待核对请求标识，不再持续保存完整新会话。

旧浏览器记录不自动上传。点击“导入本机旧对话”并确认后进入共享空间，重复导入不产生副本，原本机数据不删除。导入不接收客户端摘要；不完整消息保留展示，但不用于模型上下文。单次导入最多 2,000 条消息；无效引用不迁移，原文字保留。

## 验证

自动化：`python -m unittest discover -s tests -q`；前端运行 `npm test` 与 `npm run build`。

真实联调会调用当前配置的模型与 Milvus，并保留两份测试会话，不上传、修改或删除知识库文档：

```powershell
.\.venv\Scripts\python.exe -m scripts.check_live_conversations
```

结果在 `output/live_conversations_report.json`。默认上下文配置下，第 8 轮触发摘要；测试包含普通追问、知识库指代追问、模式切换、摘要后信息回忆及引用原文核对。完整报告包含测试对话，仅留在本地。

启动前后端后，在 `front/` 执行 `node scripts/browser-check.mjs`，读取上述真实会话验证摘要、引用、刷新、共享历史和移动布局。可用 `FRONT_URL` 指定前端地址、`CHROME_PATH` 指定已安装 Chrome；截图在 `front/artifacts/`。
