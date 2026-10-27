# 项目实施记录

> 本文记录已经实际完成并提交到 Git 的工作，不是未来规划清单。

## 1. 记录范围

本文围绕“用户信息不足时，Agent 自动追问，直到信息足够再回答”的目标，记录从 Grill Engine 到 P05 的实际实现结果：

| 阶段 | 实际定位 | Git 提交 | 状态 |
|---|---|---|---|
| Grill Engine | 实现信息完整性检查和多轮追问 | `0689322` | 已完成 |
| P01 | 统一 Web、CLI、旧 Agent、MCP 的 Agent 执行架构 | `9a3b88a` | 已完成 |
| P02 | 完成配置、依赖、Docker、离线降级和运行验收 | `d232d9c` | 已完成 |
| P03 | 持久化会话、生产运行加固和安全验收 | `b535778` | 已完成；详见 [P03 实施文档](p03-implementation.md) |
| P04 | 小型平台、JWT、Redis 和 Kubernetes 部署层 | `87715ca` | 已完成；详见 [P04 实施文档](p04-implementation.md) |
| P05 | 可观测性、CI、安全加固、备份恢复和交付验收 | 本次交付提交 | 已完成；详见 [P05 实施文档](p05-implementation.md) |

实施时间：2026-10-26。

## 2. Grill Engine：追问能力落地

### 2.1 实际完成的代码

新增并接入了 `core/grill_engine.py`，主要实现了：

- 使用 `TaskProfile` 定义不同任务需要哪些信息。
- 使用 `FieldSpec` 定义字段名称、描述、别名、默认值和候选项。
- 使用 `GrillContext` 保存跨轮次已收集的信息。
- 使用 `GrillResult` 统一返回执行、追问、候选、降级等结果。
- 支持关键字段和可选字段两种优先级。
- 支持用户自然语言中的字段提取，例如“晚餐”“没有忌口”“鸡胸肉 200 克”。
- 支持候选项，例如早餐、午餐、晚餐。
- 支持默认值，例如人数默认 1 人、烹饪时间默认 30 分钟内、菜系默认不限。
- 设置最大追问次数，避免对话无限循环。
- 关键字段始终优先询问，信息不足时不会直接猜测。

当前已经配置的任务画像包括：

#### 餐食规划 `meal_planner`

关键字段：

- 餐次
- 过敏原或忌口

可使用默认值的字段：

- 饮食目标
- 人数
- 烹饪时间
- 菜系偏好

#### 热量查询 `calorie_query`

关键字段：

- 食物名称

可使用默认值的字段：

- 食物份量，默认 100g
- 生重或熟重，未说明时使用提示性默认口径

### 2.2 工作流接入

Grill Engine 已接入 `core/workflow.py` 的 LangGraph 状态图，实际执行顺序为：

```text
意图识别
  ↓
记忆检索
  ↓
Grill 信息完整性检查
  ├─ 信息不足 → 返回追问
  └─ 信息足够 → 进入工具规划和答案生成
```

追问不会写入长期知识记忆，只有最终回答才会进入长期记忆流程，避免把“你想吃哪一餐”这类中间问题当成知识保存。

### 2.3 前端配合改造

前端会读取接口返回的 `options`，将候选项渲染为可点击按钮。

例如后端返回：

```json
{
  "type": "clarification",
  "target_field": "meal_type",
  "answer": "你想安排哪一餐？",
  "options": ["早餐", "午餐", "晚餐"]
}
```

浏览器会直接显示早餐、午餐、晚餐按钮，用户不必手动输入。

### 2.4 实际效果

已经实现并验证以下流程：

```text
用户：我想减肥
Agent：你想安排哪一餐？

用户：晚餐
Agent：你有需要避开的食物或过敏原吗？

用户：没有
Agent：信息收集完成，进入最终回答流程
```

## 3. P01：统一 Agent 执行架构

### 3.1 改造前的实际问题

改造前存在多套执行入口：

```text
Web → front/app.py 自己初始化和调用 Workflow
CLI → main.py 调用旧 AgentExecutor/ReAct
旧业务代码 → agent_executor.py
MCP → local_server.py 自己实现检索逻辑
```

这意味着同一个问题可能经过不同代码路径，工具和会话逻辑也存在重复实现。

### 3.2 实际完成的代码

新增 `core/conversation_runtime.py`，形成统一会话运行时 `ConversationRuntime`。

它实际负责：

- 接收和校验用户问题。
- 根据 `user_id` 管理会话。
- 维护多轮对话历史。
- 生成 LangGraph 初始状态。
- 调用统一 Workflow。
- 提取最终回答。
- 处理 Grill 追问状态。
- 记录响应耗时和检索次数。
- 返回统一的 `ConversationResponse`。

新增 `core/tool_registry.py`，形成统一工具注册中心。

目前注册的工具包括：

- `retrieval_tool`：本地知识库检索。
- `calorie_query`：热量查询。
- `meal_planner`：餐食规划。
- `web_search`：Tavily 联网搜索。

工作流不再自己维护大量工具分支，而是通过统一接口执行：

```text
工具名称 + 查询内容 + Grill 上下文
              ↓
        ToolRegistry
              ↓
        对应工具处理器
```

### 3.3 兼容旧代码

修改了 `agent/agent_executor.py`，保留原有的：

```python
create_agent_executor().invoke({"input": "..."})
```

但这个旧接口现在只是兼容适配器，实际会转发到 `ConversationRuntime`，不会再创建第二套独立 ReAct Agent。

这样既完成了架构统一，也避免一次性破坏已有调用方。

### 3.4 三类入口统一后的结构

```text
Web /ask
CLI main.py
旧 AgentExecutor
        ↓
ConversationRuntime
        ↓
LangGraph Workflow
        ↓
Grill + Memory + ToolRegistry
        ↓
统一回答结果
```

MCP 是工具协议入口，不负责完整的用户会话；它复用 `core.tool_registry` 中的标准检索处理器，避免再实现一套检索逻辑。

### 3.5 P01 的实际收益

- Web 和 CLI 使用同一套核心逻辑。
- 追问状态不再只存在于某个入口内部。
- 工具只实现一次，减少重复代码。
- 返回结构统一，前端和其他调用方更容易接入。
- 通过依赖注入可以替换 Workflow 和 Memory，便于自动化测试。
- 旧入口仍可使用，降低迁移风险。

## 4. P02：配置、部署和运行稳定性

### 4.1 统一配置

修改了 `config.py`，使用 Pydantic Settings 管理配置，并新增 `.env.example`。

实际统一管理的配置包括：

- `ZHIPUAI_API_KEY`：智谱模型 Key。
- `TAVILY_API_KEY`：联网搜索 Key。
- `LLM_MODEL`：模型名称。
- `EMBEDDING_MODEL`：Embedding 模型名称。
- `USE_GRAPHRAG`：是否开启 Neo4j GraphRAG。
- `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`：Neo4j 连接配置。
- `ENABLE_MCP`、`LOCAL_MCP_SERVER`：MCP 配置。

配置缺失时会给出启动警告，而不是产生难以定位的错误。

### 4.2 离线降级能力

实际增加了无模型 Key 时的离线行为：

- 应用仍然可以启动。
- 关键词“减肥、减脂、控制体重、增肌、饮食目标、健康饮食”可以识别为餐食规划意图。
- Grill 追问流程可以正常执行。
- 热量查询和餐食规划会返回参数确认或离线说明。
- 配置真实模型 Key 后，才会进入真实模型回答路径。

这使得开发、测试和演示不再强依赖外部 API Key。

### 4.3 GraphRAG 配置保护

当 `USE_GRAPHRAG=true` 但没有 `NEO4J_PASSWORD` 时，系统会明确提示 GraphRAG 配置不完整，不会静默地连接失败。

GraphRAG 仍然是可选能力，不影响基础对话和追问功能。

### 4.4 依赖整理

实际删除了当前代码没有使用的直接依赖：

- `chromadb`
- `firecrawl-py`
- `redis`

实际固定了容易产生兼容问题的版本：

- `langgraph==0.0.51`
- `mcp==1.1.3`

开发工具统一放在 `requirements.txt` 的开发安装入口中，包括 pytest、pytest-cov、black、isort 和 mypy；生产 Docker 镜像只执行项目安装，不安装开发工具。

### 4.5 Docker 部署

新增 `Dockerfile` 和 `.dockerignore`。

Docker 镜像实际使用：

- Python 3.12 slim 基础镜像。
- 项目依赖通过 `pip install .` 安装。
- Flask 监听 `0.0.0.0:5000`。
- 容器启动命令为 `python front/app.py`。

已实际构建镜像：

```text
eat-agent:p02
```

并启动容器：

```text
eat-agent-p02
127.0.0.1:5000 → 容器 5000
```

### 4.6 浏览器问题修复

真实浏览器验收时发现发送按钮把浏览器 `Event` 对象错误传给了 `sendQuestion`，导致 `.trim()` 报错。

已将事件绑定从：

```javascript
sendBtn.addEventListener('click', sendQuestion);
```

修复为：

```javascript
sendBtn.addEventListener('click', () => sendQuestion());
```

修复后重新构建镜像，并完成浏览器三轮对话验证。

## 5. P03：持久化与生产运行加固

### 5.1 实际完成的代码

P03 将“追问状态只存在进程内存中”的原型能力改造成可重启、可部署的会话服务：

- 新增 `core/persistence.py`，使用 SQLAlchemy 持久化 `conversations` 和 `messages`。
- 新增 Alembic 配置和初始迁移 `migrations/versions/0001_create_conversations.py`。
- `ConversationRuntime` 每轮从数据库恢复历史消息、当前目标和 `GrillContext`，回答后保存本轮消息和追问状态。
- 引入 `conversation_id` 和 `request_id`，支持前端恢复会话和请求级排查；同一请求重复保存具备幂等性。
- 使用会话级锁保护并发请求，避免同一会话的上下文交叉写入。
- 显式 SQLite URL 会自动建表，方便本地开发和单元测试；生产 PostgreSQL 仍由 Alembic 管理。

### 5.2 API 与安全加固

- 新增 `/healthz` 和 `/readyz`，分别用于进程存活和数据库就绪检查。
- 支持通过 `X-API-Key` 开启 API Key 鉴权；首页和健康检查保持可访问。
- 增加请求体大小限制、JSON 对象校验、统一错误结构和 `X-Request-ID`。
- 增加按客户端地址的滑动窗口限流。
- 增加 JSON 结构化请求日志，记录请求 ID、路径、状态码和响应时间。
- 会话按 `user_id` 隔离；其他用户访问已有 `conversation_id` 返回 HTTP 403。
- 前端将 `conversation_id` 持久化到浏览器 `localStorage`，后续请求继续使用同一会话。

### 5.3 部署改造

- `docker-compose.yml` 新增 PostgreSQL、应用服务、持久化卷和健康检查。
- 应用容器启动时先执行 `alembic upgrade head`，再使用 Gunicorn 启动 2 个 worker。
- 数据库和应用分别通过 Compose 服务名通信，应用数据和 PostgreSQL 数据使用命名卷保存。
- 最终镜像为 `eat-agent:p03`，实际运行地址为 `http://127.0.0.1:5000`。

### 5.4 P03 专项测试

新增 `test_p03_persistence.py`，覆盖：

- 会话和消息往返持久化。
- 相同 `request_id` 重复写入的幂等性。
- 新 Runtime 实例恢复旧 Runtime 写入的历史消息。
- 不同用户访问同一会话时的权限拒绝。

## 6. 实际验收记录

### 6.1 自动化测试

在 Linux Docker 生产镜像环境内执行：

```text
17 passed in 1.66s
```

测试覆盖了：

- Grill 首轮追问。
- 多轮字段收集。
- 关键字段缺失处理。
- 默认值处理。
- 最大追问次数和降级。
- 新意图切换。
- 会话运行时和统一架构契约。
- P03 数据库持久化、重启恢复和用户隔离。

### 6.2 API 验收

使用同一个 `user_id` 调用 `/ask`：

```text
我想减肥 → 追问餐次
晚餐 → 追问过敏原
没有 → 进入最终回答路径
```

首页 `GET /` 返回 HTTP 200，`POST /ask` 返回 HTTP 200。

P03 还实际验证了：

- `/healthz` 和 `/readyz` 均返回 HTTP 200。
- 开启 API Key 时，无 Key 返回 HTTP 401，正确 Key 返回 HTTP 200。
- 非法 JSON 请求体返回 HTTP 400。
- 其他用户访问已有会话返回 HTTP 403。
- 应用容器重启后，原会话继续返回下一项追问，历史没有丢失。

### 6.3 浏览器验收

在真实浏览器页面中完成：

1. 输入“我想减肥”。
2. 页面显示“早餐、午餐、晚餐”候选按钮。
3. 点击“晚餐”。
4. 页面显示过敏原追问。
5. 点击“没有过敏或忌口”。
6. 页面显示“已完成回答”。

P03 完成后又在真实浏览器中验证了“我想增肌 → 晚餐 → 没有过敏或忌口”三轮流程，候选按钮、追问状态和最终回答状态均正常。由于当前环境未配置模型 Key，最终回答使用项目已有的离线降级能力。

### 6.4 代码和交付检查

- `git diff --check` 通过。
- P03 实现已提交，提交为 `b535778`。
- 最新 Docker 容器保持运行，PostgreSQL 和应用健康检查通过。

## 7. P04：小型平台与 Kubernetes 部署层

P04 在 P03 的持久化基础上完成了小型平台能力，实际改动、验收和边界详见 [P04 实施文档](p04-implementation.md)。核心落地内容如下：

- 增加 JWT 注册、登录、刷新、退出和当前用户接口，密码使用 PBKDF2 哈希。
- 保留 API Key 兼容模式，并在 JWT 模式下强制以 Token 身份隔离用户会话。
- 增加会话创建、列表、详情和归档接口，以及前端历史会话切换。
- 增加 `users`、`refresh_tokens` 和 `idempotency_records` 数据模型，新增 `0002_platform_auth_idempotency` 迁移。
- 使用 Redis 实现共享限流和跨 worker/Pod 会话锁；Redis 不可用时保留开发环境 fallback。
- 对相同 `request_id` 直接恢复完整响应，避免重复执行 Workflow 和重复写入消息。
- Compose 新增 Redis，最终镜像为 `eat-agent:p04`。
- 新增 Helm Chart，包含 Deployment、Service、ConfigMap、Secret、迁移 Job、Redis、Ingress、HPA 和 PDB。
- 最终镜像全量测试为 `20 passed in 4.95s`，真实浏览器完成三轮追问和最终回答验收。
- 本机 Kubernetes 集群未启用，因此只完成 Helm lint/render，未宣称真实集群部署已验收。

## 8. P05：企业级运行保障与交付验收

P05 的完整实际记录见 [P05 实施文档](p05-implementation.md)。本阶段已经落地：

- Prometheus HTTP、会话、Grill、LLM 和限流指标，以及 `/metrics` 访问保护；
- 结构化日志脱敏、用户标识指纹化和敏感错误收敛；
- 生产严格安全配置校验，避免弱 JWT、通配 CORS、SQLite 或无 Redis 配置进入生产；
- 非 root 容器、只读根文件系统、capabilities drop、seccomp 和临时卷等 Helm 安全默认值；
- PostgreSQL custom-format 备份与显式确认恢复脚本；
- Grill 评测样例、P05 运行安全测试和 GitHub Actions CI；
- 最终 `eat-agent:p05` 镜像、Compose 健康检查、真实浏览器多轮追问和数据库恢复演练。

P05 实际验收结果：

```text
最终镜像全量测试：27 passed
浏览器：信息不足 → 两轮追问 → 已完成回答
PostgreSQL：custom-format backup/restore 成功
Helm：lint/render 成功
Kubernetes：本机未启用，仅完成静态验收
```

## 9. 当前已知边界

本记录只记录已经实际完成的 Grill Engine、P01、P02、P03、P04 和 P05，不把后续计划写成已完成能力。

当前仍有以下边界：

- JWT 用户认证、Refresh Token 轮换和 Redis 共享协调已在 P04 落地；完整 RBAC、企业 SSO/OIDC 和更完整审计留存仍未接入。
- CI 已增加自动检查，但 CD 发布、镜像签名、制品仓库和自动回滚仍需接入实际发布平台。
- Kubernetes 真实集群、Ingress Controller、Metrics Server、Prometheus Operator 和生产级 Redis/PostgreSQL 高可用尚未在本机验收。
- PostgreSQL 备份工具和恢复演练已完成；定时任务、对象存储、保留策略和生产级恢复演练仍需结合环境落地。
- TLS、告警、分布式链路追踪和更细粒度的数据访问策略仍需按生产环境补齐。
- 未配置模型 Key 时只能使用离线降级能力，不能获得完整的模型生成答案。

