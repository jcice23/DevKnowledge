# JC 前端

React + TypeScript + Vite，独立运行的本地个人助手界面。

## 启动

先在项目根目录启动后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

另开终端：

```powershell
cd front
npm install
npm run dev
```

浏览器打开 http://localhost:5173 。页面需通过开发服务打开，不支持双击 HTML。
开发服务默认监听 `0.0.0.0:5173`，同一局域网的设备可访问
`http://本机局域网IPv4:5173`（运行 `ipconfig` 查看连接 Wi-Fi 或网线的适配器地址）。
修改此配置后需重启 `npm run dev`。Windows 若提示防火墙访问，请允许当前可信局域网访问；
若无法连接，检查 TCP 5173 的入站规则以及路由器是否启用了访客网络或设备隔离。
后端仍只需监听 `127.0.0.1:8000`，局域网请求通过 Vite 代理转发。
默认通过 Vite 把 `/api/*` 请求去掉 `/api` 前缀后转发到 `http://127.0.0.1:8000`。
如需更换后端，将 `.env.example` 复制为 `.env.local` 并调整 `BACKEND_URL`，然后重启开发服务。
此变量只用于开发服务器；不要把模型密钥放入前端配置。

## 使用范围

- 默认知识库模式，可切换普通聊天；同一服务器会话延续上下文，知识库每轮重新检索。
- 会话及引用保存在服务器 SQLite，局域网设备共享；浏览器只保留草稿、模式、选中会话和待核对请求标识。较早历史整理为可查看的摘要。
- 旧 localStorage 会话通过“导入本机旧对话”手动导入，不自动上传或清除原记录。删除会话会从服务器删除，其他设备同步生效。
- 上传自动进入后台入库队列，面板每两秒刷新服务器文档状态；失败支持重试。原文件保存在项目 data/uploads，状态保存在 data/documents.sqlite3。没有文档删除功能。
- 请求错误真实显示，不用演示答案替代；输入期间支持中文输入法和 Shift+Enter 换行。
- Markdown 不启用原始 HTML；引用编号可打开原文面板。
- 当前使用非流式 API，所以显示“正在处理”，不伪造检索或生成阶段。

## 验证

```powershell
npm test
npm run build
```

构建输出在 `dist/`，生产部署需要另行配置 API 反向代理；本次提供本地开发运行方式。

先在项目根目录执行 `python -m scripts.check_live_conversations` 完成真实模型联调（会产生模型请求并保留测试会话）。
启动前后端后可运行 `node scripts/browser-check.mjs`，读取真实会话验证摘要、引用、刷新恢复和手机布局，不生成模拟答案。
默认使用 Windows 已安装的 Chrome，可通过 `CHROME_PATH` 指定其他本机 Chrome 路径，`FRONT_URL` 指定页面地址。
截图及报告在 Git 忽略的 `artifacts/` 目录。更多接口及配置见 [多轮上下文](../docs/conversations.md)。
