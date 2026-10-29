# 轻松食 React 前端

这是“轻松食 · Eat Agent”的移动端优先 React 前端，也是项目唯一的 Web 界面。`front/` 仅提供 FastAPI API，不再提供旧模板页面。

## 本地开发

```bash
cd frontend
npm ci
copy .env.example .env.local  # Windows
npm run dev
```

开发时打开 <http://127.0.0.1:5173>。Vite 将 `/api` 代理到 FastAPI 服务 `http://127.0.0.1:5000`。

生产环境不需要启动 5173：`npm run build` 生成的 `dist/` 会由 FastAPI 在 `http://127.0.0.1:5000` 同源托管，React API 请求也会自动切换为同源路径。

## 配置

- `VITE_API_BASE_URL=/api`：使用同源代理访问后端。
- `VITE_PROXY_TARGET=http://127.0.0.1:5000`：本地 FastAPI 地址。
- `VITE_USE_MOCK_API=false`：默认真实接口；只有显式设为 `true` 才启用 mock 预览。

## 构建

```bash
npm run build
npm run preview
```

Docker 会自动构建 React 并把产物放入 FastAPI 镜像，直接执行项目根目录的 `docker compose up -d --build` 即可使用单一的 5000 端口。

饮食记录和餐食计划目前使用独立的本机 service，页面会明确标注尚未同步到服务端；对话、认证、个人档案和个人知识库走现有 FastAPI 接口。
