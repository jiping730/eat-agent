# P04 实施文档：小型平台能力与 Kubernetes 部署层

> 状态：已完成，可交付
>
> 实施日期：2026-10-27
>
> 版本：`0.4.0`

## 1. 阶段目标

P04 面向个人企业项目的小型平台目标，在保留模块化单体的前提下补齐用户、会话、认证、跨进程协调和 Kubernetes 部署能力。

本阶段没有拆分微服务，也没有引入 Keycloak、Service Mesh、Kafka 或 Operator。Docker Compose 继续作为本地开发方式，Kubernetes + Helm 作为部署层。

目标结构：

```text
浏览器 / API 客户端
        ↓
Flask + Gunicorn 模块化单体（默认 2 worker）
        ├─ JWT 用户认证 / API Key 兼容
        ├─ ConversationRuntime
        ├─ Grill Engine 多轮追问
        ├─ PostgreSQL 会话与用户数据
        └─ Redis 共享限流与跨 worker 会话锁
        ↓
Kubernetes Service / Ingress / HPA / PDB
```

## 2. P03 到 P04 的变化

| 能力 | P03 | P04 |
|---|---|---|
| 用户身份 | 主要依赖请求头 `X-User-ID` | JWT 用户认证；保留 API Key 兼容 |
| 会话管理 | 可持久化，但缺少平台化管理接口 | 会话创建、列表、详情、归档 |
| 用户数据 | 无用户账户和密码哈希 | `users`、`refresh_tokens` |
| 重复请求 | 保存层幂等 | 运行时按 `request_id` 直接恢复完整响应，不重复执行 Workflow |
| 会话锁 | 单进程锁 | Redis 分布式锁，Redis 不可用时开发环境降级 |
| 限流 | 单进程内存 | Redis 共享滑动窗口，保留本地 fallback |
| 本地部署 | PostgreSQL + 应用 Compose | PostgreSQL + Redis + 应用 Compose |
| 集群部署 | 无 Kubernetes 资源 | Helm Chart、Deployment、Service、迁移 Job、Ingress、HPA、PDB |
| 模型不可用 | 可能返回模型失败文本 | 显式抛出异常，由 Workflow 统一进入本地餐食兜底 |

## 3. 实际代码改动

### 3.1 统一配置与依赖

修改 [config.py](../config.py)、[.env.example](../.env.example) 和 [pyproject.toml](../pyproject.toml)：

- 增加 `AUTH_MODE`，支持 `none`、`auto`、`api_key`、`jwt`、`hybrid`。
- 增加 `JWT_SECRET`、签发者和 Access/Refresh Token 有效期配置。
- 增加 `REDIS_URL` 和分布式锁超时配置。
- 版本从 P03 的 `0.3.0` 提升为 `0.4.0`。
- 增加 `PyJWT` 和 `redis` 依赖。
- 未配置模型 Key 时启动仍可用，并明确进入离线降级能力。

### 3.2 JWT 用户认证

新增 [core/auth.py](../core/auth.py)，实现 `AuthService`：

- 密码使用 PBKDF2 哈希保存，不保存明文密码。
- 生成短时效 Access Token 和长时效 Refresh Token。
- Refresh Token 以哈希形式保存，支持轮换和撤销。
- Token 中包含 `sub`、`roles`、`iss`、`iat`、`exp` 等标准字段。
- API Key 继续支持服务间调用和旧客户端迁移。
- `auto` 模式在未配置 JWT Secret 时兼容开发模式；生产 Helm 默认使用 JWT。

新增接口：

```text
POST /auth/register
POST /auth/login
POST /auth/refresh
POST /auth/logout
GET  /me
```

`/ask` 在 JWT 模式下以 Token 的 `sub` 为准，不信任请求体中的 `user_id`；两者不一致返回 403，避免越权访问他人会话。

### 3.3 Redis 共享协调能力

新增 [core/redis_support.py](../core/redis_support.py)：

- 统一创建 Redis 客户端并执行连接检查。
- 使用带 token 的 Redis 锁保护同一会话的并发请求。
- 锁释放时校验 token，避免误释放其他请求持有的锁。
- Redis 不可用时，开发环境使用本地锁；生产部署应将 Redis 作为就绪依赖。

修改 [core/rate_limiter.py](../core/rate_limiter.py)：

- 优先使用 Redis 共享滑动窗口，使多 worker、多 Pod 看到同一限流计数。
- Redis 暂时不可用时回退到本地内存限流，保证单实例开发可运行。

### 3.4 平台数据模型与迁移

修改 [core/persistence.py](../core/persistence.py)，新增模型：

- `users`：用户名、密码哈希、角色、启用状态和时间戳。
- `refresh_tokens`：Refresh Token 哈希、过期时间、撤销时间和用户关联。
- `idempotency_records`：用户、会话、请求 ID 和完整响应 JSON。

扩展 `conversations`：

- `title`：前端历史会话展示标题。
- `version`：乐观版本号，便于并发控制和排查。
- `archived_at`：软归档，不直接删除历史数据。

新增 [migrations/versions/0002_platform_auth_idempotency.py](../migrations/versions/0002_platform_auth_idempotency.py)。迁移链为：

```text
0001_create_conversations
        ↓
0002_platform_auth_idempotency
```

迁移过程中曾发现 PostgreSQL revision 字段长度限制，已将 revision 修正为不超过 32 个字符，并在最终 Compose 栈中成功执行。

### 3.5 会话运行时幂等

修改 [core/conversation_runtime.py](../core/conversation_runtime.py)：

1. 进入会话锁，防止同一会话同时处理两轮输入。
2. 根据 `conversation_id` 和用户身份恢复消息、目标和 GrillContext。
3. 先查询幂等记录；相同 `request_id` 已完成时直接返回原响应。
4. 只有新请求才执行 LangGraph Workflow。
5. 保存完整响应、消息和新版本号。
6. 释放分布式锁。

因此网络重试不会再次调用工具或模型，也不会重复插入用户消息和 Agent 消息。

### 3.6 Web API 与前端平台功能

修改 [front/app.py](../front/app.py)，新增：

```text
GET    /conversations
POST   /conversations
GET    /conversations/{conversation_id}
DELETE /conversations/{conversation_id}
```

删除接口实际执行归档，按用户身份隔离数据。

修改 [front/templates/index.html](../front/templates/index.html)、[front/static/script.js](../front/static/script.js) 和 [front/static/style.css](../front/static/style.css)：

- 增加登录、注册、退出区域。
- 使用浏览器本地存储保存 Access/Refresh Token。
- Access Token 过期时自动尝试 Refresh。
- 增加“新建会话”和历史会话选择器。
- 打开历史会话时加载消息记录。
- 保留 Grill 的候选按钮和追问状态展示。

### 3.7 离线模型降级修复

修改 [utils/llm.py](../utils/llm.py)：

- 未配置 `ZHIPUAI_API_KEY` 时显式抛出配置异常。
- 外部 LLM 调用失败时抛出统一运行时异常。
- 由 [core/workflow.py](../core/workflow.py) 统一捕获并根据已收集的 Grill 字段生成本地餐食回答。

这样模型不可用不会伪装成最终业务回答，也不会阻断追问流程；本地演示和测试可以得到可解释的降级结果。

### 3.8 Docker Compose

修改 [docker-compose.yml](../docker-compose.yml) 和 [Dockerfile](../Dockerfile)：

- 保留 PostgreSQL 命名卷。
- 新增 `redis:7-alpine` 服务、健康检查和命名卷。
- 应用等待 PostgreSQL、Redis healthy 后执行 `alembic upgrade head`。
- 应用镜像标签为 `eat-agent:p04`。
- 生产镜像只安装项目依赖，不把 pytest 等开发工具打进运行镜像。
- Gunicorn 默认 2 worker，监听 `0.0.0.0:5000`。

### 3.9 Kubernetes + Helm

新增 [deploy/helm/eat-agent](../deploy/helm/eat-agent/)：

- `Deployment`：默认 2 副本、RollingUpdate、优雅退出、资源 requests/limits。
- `Service`：ClusterIP 暴露 5000 端口。
- `ConfigMap`：非敏感配置。
- `Secret`：支持引用集群外部 Secret，不在 Git 保存真实密钥。
- 迁移 `Job`：Helm pre-install/pre-upgrade hook 执行 `alembic upgrade head`。
- Redis Deployment + Service：小型平台默认内置单副本，可通过 values 切换为外部 Redis。
- `Ingress`：默认关闭，生产按域名和 TLS 配置开启。
- `HPA`：默认关闭，开启后按 CPU 在 2～4 副本间伸缩。
- `PDB`：默认关闭，生产可设置最少可用副本。
- `/readyz` readinessProbe 和 `/healthz` livenessProbe。

PostgreSQL 默认由集群外的云数据库或独立数据库服务提供；不把数据库 StatefulSet 强行塞进应用 Chart，减少小型平台的运维耦合。

## 4. 实际验证记录

### 4.1 自动化测试

在最终 `eat-agent:p04` 运行镜像上挂载当前代码，临时安装 pytest 执行全量测试：

```text
....................                                                     [100%]
20 passed in 4.95s
```

覆盖：

- P0/P01 统一架构契约。
- Grill 首轮追问、多轮字段收集和降级。
- P03 PostgreSQL/SQLite 持久化、重启恢复和用户隔离。
- P04 JWT 往返和密码哈希。
- 相同 `request_id` 不重复执行 Workflow。
- 会话列表、归档和用户范围隔离。

新增测试文件：[test_p04_platform.py](../test_p04_platform.py)。

### 4.2 Compose 验收

实际运行：

```text
eat-agent:p04
postgres:14-alpine
redis:7-alpine
```

已验证：

- `GET /healthz` 返回 200，版本为 `0.4.0`。
- `GET /readyz` 返回 200。
- Alembic 迁移成功执行到 `0002_platform_auth_idempotency`。
- `/ask` 追问、会话列表、会话详情正常。
- 重复 `X-Request-ID` 返回相同响应，消息没有重复写入。
- JWT 模式下无 Token 返回 401，注册后 Bearer Token 可调用 `/ask`。
- Token 用户身份与请求体 `user_id` 不一致时返回 403。

### 4.3 真实浏览器验收

在 `http://127.0.0.1:5000/` 完成：

```text
输入：我想增肌
  → 页面追问：你想安排哪一餐？
  → 点击：晚餐
  → 页面追问：你有需要避开的食物或过敏原吗？
  → 点击：没有过敏或忌口
  → 页面显示：已完成回答
```

最终页面实际显示：

```text
我按晚餐、增肌、没有过敏或忌口为你安排。建议选择一份优质蛋白、两份蔬菜和适量主食；如果你愿意，我还可以继续细化菜品和克重。
```

本次浏览器环境没有配置真实模型 Key，因此最后一步验证的是项目明确设计的本地降级回答；追问字段、会话状态、候选按钮和完成状态均已通过。

### 4.4 Helm 验收

本机未安装 Helm，使用一次性 `alpine/helm:3.17.0` 容器完成校验：

```text
1 chart(s) linted, 0 chart(s) failed
helm template 渲染成功
```

本机 Kubernetes 集群当时未启用，`kubectl cluster-info` 无法连接，因此没有把真实集群 apply、Pod 滚动升级和 Ingress 访问宣称为已通过。Chart 静态 lint/render 已通过，真实集群验收是后续启用 Docker Desktop Kubernetes 后的部署步骤。

## 5. 资源清理记录

- 最终运行镜像保留为 `eat-agent:p04`。
- P04 全量测试使用 `--rm` 一次性容器，pytest 未写入生产镜像。
- 临时 JWT 验证容器已删除。
- 失败迁移版本未保留，最终迁移文件使用 `0002_platform_auth_idempotency`。
- 当前 Compose 正式资源为 PostgreSQL、Redis、eat-agent 及其数据卷。
- 未执行会删除用户数据库数据的清理操作。

## 6. 当前边界与下一步

P04 达到个人企业项目的小型平台交付基线，但仍有明确边界：

- 本机未启用 Kubernetes，真实集群验收待启用后执行。
- Chart 内置 Redis 适合小型平台起步；高可用生产环境应替换为托管 Redis 或专用 Redis 部署。
- PostgreSQL 备份、恢复演练、TLS、密钥管理和数据库高可用需要结合实际云环境补齐。
- HPA 需要集群 Metrics Server；Ingress 需要实际 Ingress Controller 和证书。
- 尚未引入完整 Prometheus 指标、告警和分布式链路追踪。
- 真实模型 Key 配置后才会使用模型生成内容；无 Key 时使用可解释的本地降级回答。
