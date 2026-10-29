# React 前端并入记录

## 范围

新版 React 前端位于 `frontend/`，作为项目唯一的 Web 界面；`front/` 仅保留 FastAPI API、认证和数据接口。旧模板页面与旧静态资源已移除。

## 运行方式

- 生产/使用：`http://127.0.0.1:5000`（FastAPI 同时托管 React `dist/` 和 API）
- React/Vite 开发：`http://127.0.0.1:5173`
- Vite 开发服务器将 `/api` 代理到 `http://127.0.0.1:5000`；5173 仅用于热更新开发。
- `VITE_USE_MOCK_API=true` 只用于显式本地预览，默认使用真实接口。

## 已完成的接入调整

- 认证请求适配后端的 `username` 字段和 JWT 刷新/退出接口。
- SSE 适配后端的 `model.delta`、`answer.completed`、`grill.clarify` 和 `error` 事件。
- 对话归档、反馈、重新生成、个人档案、资料授权和个人知识库请求适配现有 FastAPI 路由。
- 前端 API 错误处理兼容后端的 `error` / `error_code` 响应格式。
- Docker 使用 Node 构建阶段生成 `frontend/dist`，再复制到 Python 应用镜像；本地 `frontend/node_modules`、`frontend/dist` 仍不进入 Git。

## 当前边界

饮食记录和餐食计划仍由前端独立 service 保存到本机，并在页面中明确标注尚未同步到服务端；这不伪装成后端已持久化能力。

## 验证

在 `frontend/` 执行 `npm ci` 和 `npm run build` 均通过；FastAPI 生产模式统一访问 `http://127.0.0.1:5000`，浏览器开发验收可访问 `5173`。
