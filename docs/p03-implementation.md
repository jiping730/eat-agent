# P03 实施文档：持久化会话与生产运行加固

> 状态：已完成，可交付
>
> 实施日期：2026-10-26
>
> 代码提交：`b535778`
>
## 1. 阶段目标

P03 解决 P02 之后仍然存在的生产化问题：追问上下文只保存在进程内存中，应用重启或多 worker 运行时可能丢失；接口缺少统一的运行状态、安全、错误和请求追踪能力。

本阶段的交付目标是：

```text
用户提问
  ↓
恢复 conversation_id 对应的历史消息和 GrillContext
  ↓
继续 LangGraph + Grill 追问流程
  ↓
保存本轮消息、目标和追问状态
  ↓
应用重启后仍可继续对话
```

## 2. 实施前后变化

| 能力 | P02 | P03 |
|---|---|---|
| 会话历史 | 进程内存 | PostgreSQL 持久化 |
| 追问上下文 | 进程内存 | 数据库恢复 `GrillContext` |
| 运行方式 | Flask 开发服务器 | Gunicorn 2 worker |
| 数据库 | 无生产数据库 | PostgreSQL + Alembic |
| 服务检查 | 无统一就绪接口 | `/healthz`、`/readyz` |
| 请求追踪 | 无统一 ID | `request_id` + `X-Request-ID` |
| 会话标识 | 主要依赖 `user_id` | `conversation_id` + `user_id` |
| 接口安全 | 无 API Key | 可选 `X-API-Key` 鉴权 |
| 错误返回 | 各入口不统一 | 统一 JSON 错误结构 |
| 限流 | 无 | 滑动窗口限流 |
| 日志 | 普通输出 | JSON 结构化请求日志 |
| 部署 | 单容器 | Docker Compose 应用 + PostgreSQL |

## 3. 实际代码改动

### 3.1 数据持久化

新增 [core/persistence.py](../core/persistence.py)，实现 `ConversationStore`：

- `conversations` 表保存用户、当前目标、`GrillContext` 和时间戳。
- `messages` 表保存用户消息和 Agent 消息。
- 使用 `request_id` 防止同一请求重复写入。
- 访问已有会话时校验 `user_id`，不同用户会收到权限错误。
- PostgreSQL 由 Alembic 负责迁移。
- 显式 SQLite 地址自动建表，支持本地开发和测试。

新增：

- [alembic.ini](../alembic.ini)
- [migrations/env.py](../migrations/env.py)
- [migrations/versions/0001_create_conversations.py](../migrations/versions/0001_create_conversations.py)

### 3.2 会话运行时

修改 [core/conversation_runtime.py](../core/conversation_runtime.py)：

1. 接收或生成 `conversation_id`、`request_id`。
2. 从数据库读取历史消息和 Grill 上下文。
3. 将历史消息与当前用户输入合并后交给统一 Workflow。
4. 根据 Grill 结果返回追问、候选项或最终回答。
5. 将本轮输入、输出和最新上下文保存到数据库。
6. 使用会话级锁避免同一会话的并发请求交叉写入。

这样，Grill Engine 的追问能力和 P03 的数据库恢复能力连接在了一起：持久化的不只是文本历史，还包括“下一步需要询问什么”的结构化状态。

### 3.3 Web API 生产加固

修改 [front/app.py](../front/app.py)，实际加入：

- `GET /healthz`：进程存活检查。
- `GET /readyz`：数据库连接检查。
- `X-API-Key` 可选鉴权。
- `MAX_CONTENT_LENGTH` 请求体限制。
- 请求体必须是 JSON 对象。
- 统一 400、401、403、429、500 错误结构。
- `X-Request-ID` 请求追踪。
- 按客户端地址限流。
- JSON 结构化日志。

新增支持文件：

- [core/logging_config.py](../core/logging_config.py)
- [core/rate_limiter.py](../core/rate_limiter.py)

### 3.4 前端会话恢复

修改 [front/static/script.js](../front/static/script.js)：

- 首次打开页面时创建并保存 `user_id`。
- 保存 `conversation_id` 到 `localStorage`。
- 每次调用 `/ask` 都带上 `user_id` 和 `conversation_id`。
- 刷新页面后继续使用原会话，而不是创建新会话。

### 3.5 容器部署

新增 [docker-compose.yml](../docker-compose.yml)：

- `postgres` 使用 PostgreSQL 14。
- `eat-agent` 使用 `eat-agent:p03`。
- PostgreSQL 数据使用命名卷保存。
- 应用数据使用命名卷保存。
- PostgreSQL 健康后才启动应用。
- 应用启动时执行 `alembic upgrade head`。
- 应用使用 Gunicorn 2 个 worker 监听 5000 端口。

## 4. 配置项

主要配置位于 [.env.example](../.env.example)：

| 配置 | 用途 | P03 默认策略 |
|---|---|---|
| `DATABASE_URL` | 数据库连接 | Docker 中使用 PostgreSQL |
| `AUTO_CREATE_SCHEMA` | 是否自动建表 | 生产关闭，使用 Alembic |
| `APP_API_KEY` | API Key | 留空表示关闭鉴权 |
| `MAX_REQUEST_BYTES` | 请求体上限 | 65536 |
| `RATE_LIMIT_PER_MINUTE` | 每分钟请求上限 | 120 |
| `CORS_ORIGINS` | 跨域来源 | 可配置 |
| `LOG_LEVEL` | 日志等级 | `INFO` |
| `APP_VERSION` | 服务版本 | `0.3.0` |

## 5. 实际验证记录

### 5.1 自动化测试

在最终 Linux Docker 运行环境中执行：

```text
17 passed in 1.66s
```

覆盖内容：

- Grill 首轮追问和多轮字段收集。
- 默认值、降级和最大追问次数。
- P01 统一运行时契约。
- 会话持久化和幂等保存。
- 新 Runtime 实例恢复历史。
- 不同用户访问会话时拒绝。

### 5.2 API 验收

已实际验证：

- `/healthz` 返回 200。
- `/readyz` 返回 200。
- 非法请求体返回 400。
- API Key 开启时，无 Key 返回 401，正确 Key 返回 200。
- 其他用户访问已有 `conversation_id` 返回 403。
- 返回中包含 `conversation_id`、`request_id`、`type` 和 `target_field`。

### 5.3 重启恢复验收

实际流程：

```text
第一次请求：我想减肥
Agent：你想安排哪一餐？

重启 eat-agent 容器

第二次请求：晚餐
Agent：你有需要避开的食物或过敏原？
```

重启后仍能继续追问，说明数据库中的历史消息和 Grill 上下文均已恢复。

### 5.4 浏览器验收

真实浏览器完成：

```text
我想增肌
  → 点击“晚餐”
  → 点击“没有过敏或忌口”
  → 页面显示完成回答状态
```

当前环境未配置模型 API Key，因此最后一步使用项目已有的离线降级能力；追问按钮、会话提交和状态展示均正常。

## 6. 资源清理记录

交付前已完成：

- 删除临时 API Key 验证容器。
- 删除旧 P02 容器和 `eat-agent:p02` 镜像。
- 删除本次失败 Compose 切换创建的临时卷。
- 清理 Docker 未使用构建缓存。
- 保留 `eat-agent:p03`、P03 应用容器、PostgreSQL 容器和正式数据卷。

## 7. 当前边界

P03 已达到个人企业项目的可交付基线，但以下内容仍属于后续增强：

- 当前 API Key 是单实例密钥，不是完整用户认证和 RBAC。
- 限流器是单进程内存实现，多副本部署时应替换为 Redis 等共享限流器。
- 尚未接入完整指标、告警和分布式链路追踪。
- PostgreSQL 备份、恢复演练、TLS 和生产级密钥管理仍需补齐。
- 未配置模型 API Key 时，最终回答会使用离线降级能力。

