# P0-8 实施记录：测试与 CI

## 阶段目标

按照项目主线，P0-8 负责让每次代码修改都能在干净环境中完成自动回归。目标是覆盖小型平台的核心路径、失败路径、安全边界、并发幂等和浏览器对话闭环。

## 实际实现

1. 在 `pyproject.toml` 增加 pytest 标记、核心路由覆盖率配置、80% 覆盖率门槛和 Ruff 配置，并更新 `uv.lock` 纳入质量工具和浏览器 E2E 依赖。
2. 新增 `test_p08_quality.py`，覆盖：
   - Prompt Injection 文本不能绕过 Grill 必填字段。
   - 指令型文本不能凭空生成受保护的工具任务。
   - 限流器按客户端隔离。
   - 同一会话、同一 `request_id` 的并发请求保持幂等。
3. 新增 `test_browser_e2e.py`，使用 Playwright 验证：
   - 目标表达先返回建议。
   - 明确提出餐单规划后才进入 Grill。
   - 补充忌口后返回最终答案。
   - 刷新页面后恢复完整会话。
4. 更新 `.github/workflows/ci.yml`：
   - 普通测试和核心路由覆盖率检查。
   - Ruff、Black、isort、Mypy 质量检查。
   - Helm lint/template。
   - Playwright Chromium 浏览器 E2E。
   - 镜像构建和 Trivy 高危漏洞扫描。
5. 继续保持离线测试：测试使用 SQLite、Fake LLM 或安全 fallback，不依赖真实模型 Key、外部 RAG 服务和生产数据。

## 验收记录

- 全量非浏览器测试：`103 passed, 1 skipped`；核心四个模块分支覆盖率 `80.50%`，超过 80% 门槛。
- 静态质量门禁：Ruff、Black、isort、Mypy 全部通过。
- 浏览器 E2E：`1 passed`，完成目标建议、明确餐单、补充忌口和刷新恢复闭环。
- Helm：`helm lint` 和 `helm template` 均通过。
- Docker Compose 应用、PostgreSQL、Redis 健康检查保持通过。
- P0-7 之前的测试和通用意图路由测试未回归。

## 交付边界

本阶段只建立小型平台的自动化质量门禁，不实现 CD 发布、镜像签名、生产制品仓库、跨 Pod 共享熔断、多租户权限或 OIDC/企业 SSO。浏览器 E2E 作为 CI 验收项运行，真实生产浏览器监控仍属于后续平台化工作。
