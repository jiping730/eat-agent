# 项目实施记录

> 本文记录已经实际实施的工作，不是未来规划清单；已提交内容和当前工作区待提交的补充会明确区分。
>
> 后续开发以 [项目实施主线与优先级清单](implementation-roadmap.md) 为唯一基线；本文只记录实际完成情况。

## 1. 记录范围

本文围绕“用户信息不足时，Agent 自动追问，直到信息足够再回答”的目标，记录从 Grill Engine 到 P2-5 的实际实现结果：

| 阶段 | 实际定位 | Git 提交 | 状态 |
|---|---|---|---|
| Grill Engine | 实现信息完整性检查和多轮追问 | `0689322` | 已完成 |
| P01 | 统一 Web、CLI、旧 Agent、MCP 的 Agent 执行架构 | `9a3b88a` | 已完成 |
| P02 | 完成配置、依赖、Docker、离线降级和运行验收 | `d232d9c` | 已完成 |
| P03 | 持久化会话、生产运行加固和安全验收 | `b535778` | 已完成；详见 [P03 实施文档](p03-implementation.md) |
| P04 | 小型平台、JWT、Redis 和 Kubernetes 部署层 | `87715ca` | 已完成；详见 [P04 实施文档](p04-implementation.md) |
| P05（历史分期） | 可观测性、CI、安全加固、备份恢复和交付验收 | `cddb506` | 已完成；详见 [P05 实施文档](p05-implementation.md)。不等同于主线 P0-5 |
| P0-1～P0-4 补充（本轮） | 按主线收敛小型平台的统一边界、运行基础、会话治理和 FastAPI 接口 | 待提交 | 已实现并完成验收；明确暂缓企业级扩展 |
| P1-0 | P1 公共基础准备：跨模块契约、模型路由指标和评测协议 | 待提交 | 已实现并完成验收；详见 [P1-0 实施文档](p1-0-implementation.md) |
| P1-1 | 小型平台 RAG 检索质量升级 | 待提交 | 已实现并完成验收；详见 [P1-1 实施文档](p1-1-implementation.md) |
| P1-2 | 小型平台模型网关和模型路由 | 待提交 | 已实现并完成验收；详见 [P1-2 实施文档](p1-2-implementation.md) |
| P1-3 | 小型平台流式对话体验 | 待提交 | 已实现并完成验收；详见 [P1-3 实施文档](p1-3-implementation.md) |
| P1-4 | 小型平台 MCP 工具网关 | 待提交 | 已实现并完成验收；详见 [P1-4 实施文档](p1-4-implementation.md) |
| P1-5 | 小型平台安全和营养领域防护 | 待提交 | 已实现并完成专项验收；详见 [P1-5 实施文档](p1-5-implementation.md) |
| P1-6 | 小型平台知识库管理后台 | `0e5bc02` | 已实现并完成专项验收；详见 [P1-6 实施文档](p1-6-implementation.md) |
| P2-1 | 个人档案、偏好和授权上下文 | 待提交 | 已实现并完成专项验收；详见 [P2-1 实施文档](p2-1-implementation.md) |
| P2-2 | 个人对话体验增强 | 待提交 | 已实现并完成专项验收；详见 [P2-2 实施文档](p2-2-implementation.md) |
| P2-3 | 个人知识和回答质量 | 待提交 | 已实现并完成专项验收；详见 [P2-3 实施文档](p2-3-implementation.md) |
| P2-5 | 小型平台多租户基础能力 | 待提交 | 已实现并完成专项验收；详见 [P2-5 实施文档](p2-5-implementation.md) |

实施时间：2026-10-27。

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

## 9. P0-1～P0-4：小型平台补充实施记录（本轮）

本轮严格以 [项目实施主线与优先级清单](implementation-roadmap.md) 为基线，目标是让小型平台闭环可运行、可测试、可浏览器验收。以下改动已经写入工作区，当前尚未创建新的 Git 提交。

### 9.1 P0-1：统一 Agent 边界补充

- `core/tool_registry.py` 增加 `ToolResult`、`ToolSpec` 和统一 `execute_result()`，标准化工具状态、来源、错误码和 `trace_id`。
- `core/workflow.py` 改为使用标准工具结果，工具异常不会把 Python 异常细节直接返回给用户。
- `mcp_servers/local_server.py`、`core/skills/*/skill.py` 和旧 `agent/tools.py` 复用同一 Tool Registry 实现。
- CLI、Web、兼容 `WorkflowAgentExecutor` 继续通过 `ConversationRuntime` 进入同一 LangGraph Workflow。

### 9.2 P0-2：运行基础补充

- `config.py`、`.env.example` 和 Compose 增加 `CONVERSATION_TTL_DAYS` 等统一配置。
- `pyproject.toml` 补齐 FastAPI、Uvicorn、Jinja2、Werkzeug 等声明，并生成 `uv.lock`；开发测试依赖保持在 `dev` extra。
- `front/app.py` 运行入口改为 FastAPI/Uvicorn，Docker/Gunicorn 使用 `UvicornWorker`。
- 最终镜像仍使用既定标签 `eat-agent:p05`，不引入新的阶段命名，Compose 依赖 PostgreSQL 和 Redis 健康状态启动。

### 9.3 P0-3：会话治理补充

- `ConversationRecord` 增加 `expires_at`，列表、读取和写入都会阻止过期会话继续使用。
- 新增 `migrations/versions/0003_conversation_expiry.py`，为已有会话补齐默认 30 天过期时间并建立索引。
- 新增会话永久删除能力，删除消息和幂等记录；原有归档能力保留。
- 针对 SQLite 不保留时区信息的情况增加 UTC 归一化，保证本地测试和 PostgreSQL 行为一致。
- 按既定小型平台边界，租户、官方 LangGraph PostgreSQL Checkpointer 暂缓到 P2。

### 9.4 P0-4：FastAPI 和接口契约补充

- 新增 `front/schemas.py`，定义认证、会话、`/ask`、错误和 Token 的 Pydantic Schema。
- `front/app.py` 完成 FastAPI 路由、统一错误码、请求 ID、限流、CORS、JWT/API Key 认证、健康检查和指标接口。
- 保留 `/healthz`、`/readyz` 兼容路径，同时提供 `/health/live`、`/health/ready`。
- 生产 JWT 模式下用户身份来自 Token；开发模式保留 `X-User-ID` 兼容方式，OIDC/企业 SSO 和租户权限暂缓到 P2。
- 修复 FastAPI 模板中 Flask `url_for` 静态资源调用，改为 `/static/...`；给脚本增加版本参数，避免浏览器继续使用旧缓存。

### 9.5 本轮自动化与容器验收

```text
compileall：通过
全量 pytest：30 passed，1 个 Starlette 弃用警告
Docker Compose：PostgreSQL、Redis、eat-agent 均 healthy
Alembic：0001 → 0002 → 0003 成功执行
镜像：eat-agent:p05，应用以非 root 用户运行
浏览器：信息不足 → 餐次候选 → 忌口追问 → 最终回答 → 刷新后历史恢复
```

本轮没有引入或验收以下能力：多租户 `tenant_id`、OIDC/企业 SSO、官方 LangGraph PostgreSQL Checkpointer、按租户加载 Grill Profile。

## 10. P0-5：Grill v1 产品化实施记录

本阶段严格按照主线中的 `P0-5：Grill v1 产品化` 实施，不重复历史 `P05` 企业级运行保障。目标是让 Grill 从早期硬编码追问逻辑升级为可配置、可解释、可回归验证的业务规则引擎。

### 10.1 Profile 和协议

- 新增 `config/grill_profiles/meal_planner.json` 和 `config/grill_profiles/calorie_query.json`，启动时通过 Pydantic 校验并加载，按任务选择当前最高版本。
- `FieldSpec` 支持枚举、数字、日期、自由文本、布尔值、范围、长度、默认值和置信度阈值。
- `GrillResult` 增加 `schema_version`、`task`、`profile_version`、`confidence`、`reason`、`issues` 和 `task_queue`，统一输出 `clarify`、`execute`、`pending_confirmation`、`fallback`、`reject` 等决策。
- `ConversationResponse` 和 API `AskResponse` 暴露完整 `grill` 决策，前端/调用方不再只能依赖自然语言文本判断是否继续。

### 10.2 规则和上下文治理

- 增加字段值校验、低置信度拦截、依赖规则和冲突规则；安全字段冲突时不得进入工具执行。
- `FieldState` 记录值来源、置信度和证据，区分用户输入、默认值、推断值和拒答。
- 用户对关键字段明确拒答时返回 `reject`；未知回答继续追问，不把“不知道”当作有效字段。
- 用户切换意图时清理旧任务字段并记录 `previous_intent`；同一条消息识别多个已支持任务时建立顺序任务队列。
- Profile 要求确认时进入 `awaiting_confirmation`，只有收到确认消息后才返回 `execute`。
- Workflow 将 `reject`、`switch`、`multi_task` 与其他阻断动作一并导向追问响应节点，只有 `execute` 可以规划和执行工具。

### 10.3 评测和验证

- `evaluation/grill_cases.json` 扩展为 34 条黄金对话，覆盖缺字段、默认值、类型解析、拒答、未知回答、冲突、换题和热量查询。
- 新增 `test_p05_grill_v1.py`，覆盖配置加载、统一协议、字段类型、低置信度、冲突、拒答、确认、换题、多任务和自定义 Profile。
- Grill 专项测试和历史回归：`62 passed`。
- 全量项目测试：`75 passed`，仅保留 1 个 Starlette/httpx 弃用警告。
- 全量测试使用全新临时 SQLite 数据库，避免复用旧数据库文件导致迁移列缺失。

### 10.4 本阶段边界

- 当前只实现全局 Profile 注册表，不实现按租户加载 Profile；该能力与 `tenant_id` 一并延期到 P2。
- 多任务采用顺序任务队列，不实现并行多 Agent 编排。
- Profile 管理仍是文件配置，不增加在线管理后台或配置中心。

## 11. P0-6：工具执行可靠性实施记录

本阶段严格按照主线中的 `P0-6：工具执行可靠性` 实施，目标是让工具调用具备统一契约、失败隔离、有限重试和可追踪审计能力，同时保持当前小型平台的模块化单体边界。

### 11.1 工具契约与权限

- `core/tool_registry.py` 继续作为唯一工具执行边界，现有知识库、热量查询、餐食规划和联网搜索全部通过 Registry 注册。
- `ToolSpec` 增加输入 Schema、输出 Schema、超时、最大尝试次数、是否允许重试、调用方和业务意图白名单。
- 默认工具使用 Pydantic 输入模型，并对输入进行运行时校验；输出统一为 `ToolResult`，保留旧的纯文本 `execute()` 兼容入口。
- 未注册工具、未授权调用方和不匹配业务意图的调用在真正执行前被拒绝；MCP、Skill、旧入口和 Workflow 均明确标识调用方。

### 11.2 超时、重试和熔断

- 工具 handler 在受控线程池中运行，默认单次超时 15 秒。
- 仅对超时、连接错误和明确的临时错误进行重试；参数、权限、配置错误不重试。
- 默认最多 3 次尝试，使用指数退避和轻量随机抖动；当前工具均为查询型、可安全重试。
- 每个工具维护 `CLOSED`、`OPEN`、`HALF_OPEN` 状态，默认连续 5 次失败后熔断，30 秒后允许探测。
- 熔断状态第一版为进程内状态，符合小型平台目标；跨 Worker/Pod 的共享熔断状态暂缓到后续规模化阶段。

### 11.3 结果、来源和审计

- `ToolResult` 增加 `status`、`error_code`、`trace_id`、`attempts`、`duration_ms` 和 `sources`。
- 本地知识库结果携带文档来源，联网搜索结果携带 URL/标题，离线降级和规则工具也携带来源类型。
- 工具异常只返回统一安全错误，不把 Python 异常信息或堆栈直接暴露给用户。
- 通过现有 JSON 日志记录 `tool_execution` 事件，包括工具、调用方、状态、错误码、追踪 ID、请求/会话关联 ID、耗时、尝试次数和来源数量；用户标识使用指纹化值。

### 11.4 配置和 Workflow 接入

- 新增 `TOOL_DEFAULT_TIMEOUT_SECONDS`、`TOOL_MAX_ATTEMPTS`、`TOOL_RETRY_BASE_DELAY_MS`、`TOOL_CIRCUIT_FAILURE_THRESHOLD`、`TOOL_CIRCUIT_RECOVERY_SECONDS` 和 `TOOL_EXECUTOR_MAX_WORKERS` 配置。
- Workflow 执行工具前继续受 Grill `execute` 门禁，并将请求、会话、用户和当前意图传入 Registry。
- 工具失败不会再作为正常业务数据交给 LLM；Workflow 返回安全降级提示，同时保留结构化工具结果供 API 和日志使用。
- Compose 应用镜像更新为 `eat-agent:p06`。

### 11.5 P0-6 验收记录

- 新增 `test_p06_tool_reliability.py`，覆盖输入校验、调用方权限、超时、重试、熔断、未知工具、安全文本和审计关联。
- P0-6 专项测试：`8 passed`。
- 全量项目测试：`83 passed`，保留 1 个 Starlette/httpx 弃用警告。
- 使用全新临时 SQLite 数据库执行回归，避免旧本地数据库缺少 P03/P04/P05 迁移列影响测试。
- Python 3.12 AST 语法检查通过，`eat-agent:p06` 镜像构建成功。
- Docker Compose 中 PostgreSQL、Redis 和 `eat-agent:p06` 均为 healthy，`/health/live` 与 `/health/ready` 均返回 200。
- 真实浏览器回归通过：新会话完成“信息不足 → 餐次追问 → 忌口追问 → 最终回答”，刷新页面后完整会话仍可恢复。

### 11.6 本阶段边界

- 不新增 Agent 框架、任务队列或工具微服务。
- 不实现跨 Pod 共享熔断状态、在线工具市场和租户级工具策略；这些能力留到后续规模化阶段。

## 12. P0-8：测试与 CI 实施记录

P0-8 严格按照 [项目实施主线](implementation-roadmap.md) 中的“测试和 CI”执行，目标是让小型平台的核心能力具备自动回归、安全专项、并发专项和浏览器闭环验收能力。

- `pyproject.toml` 增加 pytest 标记、核心路由覆盖率配置、80% 覆盖率门槛和 Ruff 配置，`uv.lock` 纳入质量工具和浏览器 E2E 依赖。
- 新增 `test_p08_quality.py`，覆盖 Prompt Injection、Grill 门禁、限流隔离和并发幂等。
- 新增 `test_browser_e2e.py`，覆盖目标建议、明确餐单规划、补充忌口和刷新恢复。
- `.github/workflows/ci.yml` 增加覆盖率、Ruff、Black、isort、Mypy、Playwright Chromium、Helm 和镜像扫描门禁。
- P0-8 验收：全量非浏览器测试 `103 passed, 1 skipped`，核心四个模块分支覆盖率 `80.50%`；Ruff、Black、isort、Mypy、Helm 和浏览器 E2E 均通过，其中浏览器 E2E 为 `1 passed`。

本阶段仍不实现 CD 发布、镜像签名、生产制品仓库、多租户、OIDC/企业 SSO 和跨 Pod 共享熔断。

## 13. P1-1：RAG 检索质量升级实施记录

本阶段严格按照主线中的 `P1-1：升级 RAG 检索质量` 实施，目标是在不引入 Qdrant、任务队列或在线管理后台的前提下，让小型平台拥有可重复构建、可回滚、可解释和可评测的本地知识库检索链路。

### 13.1 文档入库和版本治理

- 新增 `rag/ingestion.py` 和 `python -m rag.ingestion` CLI，支持读取 `.txt` 文档、BOM/空白/换行清洗、段落与长文本切分、内容去重和访问组元数据。
- 每个文档片段携带 `document_id`、`content_hash`、`version`、`chunk_id`、标题、源文件和 `access_groups`，便于来源追踪和后续权限策略接入。
- 版本写入 `versions/<version>/manifest.json` 与 `corpus.json`，通过 `current.json` 原子切换当前版本；发布前后保留历史版本，支持 `rollback_version()` 回滚。
- 访问组可通过 CLI 重复传入 `--access-group`，未指定时默认为 `public`。

### 13.2 检索、重排和工具接入

- `rag/retriever.py` 增加确定性查询改写，统一全角文本并处理卡路里/热量、减脂/减肥、减重/减肥等同义词。
- 增加纯 Python BM25 风格词法召回，和既有 FAISS 相似度召回合并；FAISS 不可用或尚未构建时，词法召回仍可工作。
- 增加轻量确定性重排器，按查询词覆盖率、短语命中和标题命中修正多路召回结果。重排逻辑独立，未来可以替换为 BGE/Cohere，不改变上层协议。
- 在召回前执行 `access_groups` 过滤，结果增加 `retrieval_score`、`retrieval_method`、`query_rewrite`、`rerank_score` 和 `rerank_method`。
- `retrieve_with_contract()` 返回 `RetrievalResponse`、`RetrievedDocument` 和 `SourceRef`；Tool Registry 继续保留旧纯文本 API，同时向工具结果暴露来源、版本、片段和分数。

### 13.3 黄金评测和测试

- 新增 `evaluation/rag_cases.json`，覆盖来源证据、查询改写、多路召回和过敏原安全主题。
- 新增 `test_p1_rag.py`，覆盖清洗去重、版本发布回滚、权限过滤、查询改写、向量兼容、重排元数据和结构化来源。
- 新增 `test_p1_rag_eval.py`，用黄金集验证目标来源进入 Top-K，避免只验证“有结果”而不验证“结果正确”。
- `.github/workflows/ci.yml` 将 `rag/ingestion.py`、`rag/retriever.py` 纳入 Black、isort 和 Mypy；Ruff 继续扫描整个 RAG 包。

### 13.4 P1-1 验收记录

```text
P1-1 专项与公共契约测试：11 passed
Python 3.12 容器环境执行，RAG 词法/向量兼容和黄金来源断言通过
```

本阶段没有引入 `rank_bm25`、Qdrant、pgvector、在线 Reranker 或异步索引队列；这些能力会在数据规模和部署形态明确后再增加，避免偏离小型平台目标。

## 14. P1-2：模型网关和模型路由实施记录

本阶段严格按照主线中的 `P1-2：模型网关和模型路由` 实施，目标是把 Workflow 的模型调用收敛到统一网关，同时保持无 API Key 时的离线降级和旧版智谱适配器兼容。

### 14.1 网关和 Provider

- `utils/llm.py` 新增 `ModelGateway`、`GatewayResponse`、`ModelUsage` 和 `GatewayLLM`。
- 通过 LiteLLM 统一调用 Provider，默认使用智谱 OpenAI-compatible API；主模型由 `LLM_MODEL`、`LLM_INTENT_MODEL` 和 `LLM_ANSWER_MODEL` 配置。
- 支持 `LLM_FALLBACK_MODELS` 和 `LLM_FALLBACK_PROVIDER` 配置备用模型；路由结果使用既有 `ModelRouteDecision` 契约记录。
- Workflow 最终回答改用 `GatewayLLM`，旧 `CustomZhipuChat` 保留作为兼容适配器，不再作为主链路入口。

### 14.2 任务路由和可靠性

- 高置信度的明确意图继续走本地确定性路由；低置信度请求在配置了 Key 时使用低成本 `intent` 模型补充分类，模型输出必须通过 `RequestIntent` 校验，异常自动回退到本地分类。
- `answer` 任务默认使用回答模型，支持按任务切换模型，不让意图识别和复杂回答共用不可控的单一配置。
- 每个候选模型支持超时和有限指数退避重试；主模型失败后按配置顺序切换备用模型。
- 记录 Provider、模型、任务、路由、尝试次数、Token、成本、耗时和错误类型；不记录 Prompt、用户输入或 API Key。

### 14.3 Token 和费用预算

- `InMemoryBudgetStore` 按 UTC 日期和用户指纹记录 Token/费用使用量，支持预留、成功结算和失败释放，避免失败请求长期占用预算。
- `LLM_USER_DAILY_TOKEN_LIMIT` 与 `LLM_USER_DAILY_COST_LIMIT` 默认关闭（0），配置后在调用前拒绝超预算请求。
- 预算为进程内实现，适用于当前小型平台；多 Worker/Pod 共享额度需要后续迁移到 Redis 或数据库。

### 14.4 配置、测试和验收

- `config.py`、`.env.example` 增加 Provider、模型、超时、重试、Token、费用和意图模型配置。
- `pyproject.toml` 和 `uv.lock` 纳入 LiteLLM 及其锁定依赖。
- 新增 `test_p1_model_gateway.py`，覆盖主模型路由、低成本意图路由、失败重试、备用模型切换、预算拦截和非法意图输出回退。
- P1-2 专项及相关观测回归：`16 passed`。

本阶段没有引入独立模型微服务、跨 Pod 预算中心、复杂 Provider 插件市场或在线路由管理后台。

## 15. P1-3：流式对话体验实施记录

本阶段严格按照主线中的 `P1-3：流式对话体验` 实施，目标是在现有小型平台单体架构内提供可观察、可停止、可恢复的流式对话体验。完整实现说明见 [P1-3 实施文档](p1-3-implementation.md)。

### 15.1 流式运行时

- 新增 `core/streaming.py`，统一 SSE 事件、连续序号、请求 ID、会话 ID 和 Trace ID。
- `ConversationRuntime.ask_stream()` 通过后台线程和队列复用同步 Workflow，并保留会话锁、Redis 协调锁、幂等检查和最终持久化。
- 客户端停止或断开时传递取消事件，Workflow 节点和模型流式调用在安全检查点停止；已取消的半成品不会保存为正式 assistant 回答。

### 15.2 阶段事件和模型增量

- Workflow 对理解、记忆检索、工具调用、追问和最终回答发出阶段事件，前端显示“正在理解”“正在检索”“正在整理”“正在生成”等状态。
- `ModelGateway` 和 `GatewayLLM` 增加流式调用，首个增量输出前仍支持 P1-2 的重试和备用模型，输出后不切换模型。
- `answer.completed` 返回完整回答和消息 ID，`conversation.completed` 标记本轮完成。

### 15.3 用户操作和历史

- 新增 `/ask/stream`、重新生成和消息反馈接口，旧 `/ask` 保持兼容。
- 重新生成复用最近一轮已持久化的请求意图和 Grill 上下文，只追加新的 assistant 结果，不重复保存最近的用户消息；消息反馈按用户和消息唯一 upsert。
- 新增 `message_feedback` 表和 `0004_streaming_feedback` 迁移；会话详情携带消息元数据，刷新页面后可以恢复历史消息和操作。
- 前端使用浏览器原生 `fetch + ReadableStream + AbortController`，没有新增前端框架或独立流式服务。

### 15.4 本阶段验收记录

```text
P1-3 专项测试：5 passed
P1-2 模型网关回归：4 passed
全量非浏览器测试：123 passed
浏览器 E2E：1 passed
SSE 实际接口验收：事件序号连续，反馈、重新生成和历史消息 ID 返回正常
前端 JavaScript 语法检查：通过
Black / isort / Ruff / Mypy 变更范围检查：通过
```

本阶段没有引入跨节点流式接管、断点续传、消息版本树、反馈分析后台或 WebSocket/消息队列；这些能力留待平台规模和并发需求明确后再评估。

## 16. P1-4：MCP 工具网关实施记录

本阶段严格按照主线中的 `P1-4：MCP 工具网关` 实施，目标是在当前小型平台单体架构内，将本地 MCP Server 接入主 Workflow，并复用 Tool Registry 的统一执行边界。完整实现说明见 [P1-4 实施文档](p1-4-implementation.md)。

### 16.1 注册中心和工具发现

- 新增 `core/mcp_gateway.py`，实现配置驱动的 `McpServerRegistry` 和 `McpToolGateway`。
- 默认以 stdio 启动 `nutrition_local`，完成 MCP Client 初始化、工具发现、版本记录和 Session 生命周期管理。
- MCP 工具以 `{server_name}.{tool_name}` 保留全限定名；与既有 Workflow 逻辑同名的工具保持原名称并由 MCP 实现替换。

### 16.2 统一执行边界

- MCP 工具转换为现有 `ToolSpec`，继续复用调用方权限、意图权限、输入 Schema、超时、重试、熔断和审计。
- 增加 MCP 输出 Schema 校验和 MCP 来源信息，禁止任意工具暴露。
- 修复 stdio Server 日志写入 stdout 的协议污染问题，MCP JSON-RPC stdout 只保留协议帧。
- MCP 依赖采用延迟加载；MCP 不可用时保留本地工具回退，不影响应用启动。

### 16.3 配置和验证

- `.env.example`、`docker-compose.yml` 增加 MCP Server 名称、允许工具、Server JSON 和启动超时配置。
- 已在 Python 3.12 Docker 环境验证 stdio Server 注册、工具发现、调用、统一 Tool Registry 执行和 Session 关闭。
- P1-4 专项测试：`4 passed`；全量非浏览器测试：`127 passed, 1 skipped`。
- 真实 `/ask` 验收通过：主 Workflow 的 `calorie_query` 同时产生 MCP 内层和 Workflow 外层审计，最终接口返回 `200`。
- 本阶段未修改前端资源；P1-3 浏览器 E2E 回归基线保持 `1 passed`。

本阶段没有引入远程 MCP 服务发现、跨节点 Session、独立 MCP 网关微服务或在线工具管理后台。

## 17. P1-5：安全和营养领域防护实施记录

本阶段严格按照主线中的 `P1-5：安全和营养领域防护` 实施，目标是在小型平台单体架构内形成“输入检查 → 工具前门禁 → 不可信内容隔离 → 输出校验”的统一安全链路。完整说明见 [P1-5 实施文档](p1-5-implementation.md)。

### 17.1 安全策略和 Workflow 接入

- 新增 `core/safety_guard.py`，统一输出 `SafetyDecision`，识别 Prompt Injection、敏感信息、过敏原和医疗风险。
- 用户输入在意图识别前脱敏；高风险医疗/药物问题直接返回专业人士提示，不进入检索、Grill 或工具。
- 工具执行前再次检查注入和高风险内容，被阻止时不调用 Tool Registry/MCP。
- RAG、MCP、GraphRAG 和记忆内容按不可信数据隔离，指令样式片段不会作为可执行指令交给模型。

### 17.2 营养领域输出保护

- 检查常见过敏原与用户已声明限制的冲突，冲突时阻止推荐并显示强提醒。
- 检查带单位的营养数字；有来源时返回 `sources` 并附加参考来源，没有来源时显示待核验提示。
- 涉及慢性病、特殊人群或药物上下文时添加医疗免责声明；停药、剂量、治疗、诊断和相互作用问题直接升级专业人士。
- `ConversationResponse` 和 API `AskResponse` 增加 `safety`、`sources` 字段，调用方可以基于结构化结果处理风险，不依赖自然语言猜测。

### 17.3 用户记忆治理

- `core/persistence.py` 新增 `memory_consents`、`user_memories`，新增 `0005_memory_governance` 迁移。
- 记忆默认未授权；授权后才保存和检索长期记忆，撤回时删除数据库记录和短期缓存。
- 新增 `/memory/consent`、`/memory`、`/memory/export` 及 `/me/memory/*` 兼容路径，复用现有用户身份隔离。
- 记忆写入前再次脱敏，支持当前用户导出和永久删除。

### 17.4 P1-5 验收记录

```text
P1-5 专项测试：6 passed
Ruff：通过
git diff --check：通过
```

本阶段没有引入独立风控微服务、第三方内容安全平台、医疗诊断模型、人工坐席、跨租户隐私中心或复杂合规留存系统；这些能力按小型平台目标留待后续规模化阶段。

## 18. P1-6：知识库管理后台实施记录

本阶段严格按照主线中的 `P1-6：知识库管理后台` 实施，目标是把 P1-1 已具备的版本化 RAG 入库能力升级为可审核、可发布、可回滚和可分析的小型平台管理闭环。

### 18.1 知识文档治理

- `core/persistence.py` 新增 `knowledge_documents`、`knowledge_document_versions`、`knowledge_builds` 和 `knowledge_retrieval_events` 数据模型。
- 新增 `0006_knowledge_base_management` Alembic 迁移。
- 新增 `core/knowledge_base.py`，管理文档上传、草稿、审核通过、驳回、发布和下线状态。
- 同一文件名重复上传会创建新版本，不覆盖已发布版本；审核前线上继续使用旧版本。
- 支持 `.txt` 和 `.md` UTF-8 文档、标题、访问组和内容哈希；限制单文档大小，拒绝路径穿越和不支持的扩展名。

### 18.2 索引构建和版本发布

- 复用 `rag/ingestion.py` 的清洗、分块、去重和原子版本发布能力，新增从数据库审核内容构建语料的入口。
- 索引构建记录准备、收集、发布和完成阶段，以及进度、文档数、分块数和失败原因。
- 发布只纳入审核通过文档；已有线上文档在新版本审核期间继续保留已发布版本。
- 支持按索引版本或构建任务 ID 回滚，保留历史版本，不删除旧索引。
- 当前采用同步构建，适合个人企业项目和小型平台；大文件解析、批量向量化和异步任务队列留到 P2。

### 18.3 管理 API 和页面

- 新增 `/admin/knowledge` 管理页面。
- 新增文档上传、列表、详情、审核、发布、下线接口。
- 新增索引构建、构建进度、构建历史和回滚接口。
- 新增检索测试接口，返回命中文档、来源、证据片段和当前索引版本。
- 新增命中分析接口，统计总查询数、命中查询数、命中率和高频文档。
- 管理权限复用现有 JWT/API Key：`admin`、`knowledge_admin`、`service` 角色可操作，也可通过 `KNOWLEDGE_ADMIN_USER_IDS` 配置管理员用户 ID。

### 18.4 实际验收

```text
P1-6 专项测试：1 passed
P1-5 + P1-6 回归：7 passed
Ruff：通过
Mypy（变更范围）：通过
git diff --check：通过
```

当前主机的临时目录权限会阻塞 `tempfile.mkstemp`，因此本机未重复宣称真实索引写盘测试通过；底层 RAG 入库/原子发布能力沿用 P1-1 已验收实现，管理服务专项测试隔离验证了生命周期、版本治理、发布、回滚和分析逻辑。

### 18.5 本阶段边界

- 不引入 Celery、Arq、Temporal 或独立知识库服务。
- 不实现完整 RBAC、租户级知识库、对象存储和文档格式解析集群。
- 不把检索查询全文写入回答内容，只保存查询摘要、访问组和命中文档 ID。

## 19. P2-1：个人档案与偏好中心实施记录

本阶段以个人长期使用为目标，把长期个人信息从对话上下文和长期记忆中独立出来，并在用户明确授权后提供给 Grill 和回答生成流程。

### 19.1 数据与授权

- 新增 `user_profiles`，保存身高、体重、目标体重、年龄、活动量、健康目标、过敏原、饮食偏好、常用食材、餐数和预算。
- 新增 `user_profile_events`，只记录操作类型和字段名，不记录敏感字段的新旧值。
- 新增 `0007_personal_profile` Alembic 迁移。
- 个人档案默认未授权；撤回授权或删除档案时清空档案内容。
- 个人档案不与 `user_memories` 混用，避免把临时对话错误保存为长期偏好。

### 19.2 API 与页面

- 新增 `GET /me/profile`、`PUT /me/profile`。
- 新增 `POST /me/profile/consent`、`GET /me/profile/export` 和 `DELETE /me/profile`。
- 新增 `/profile` 页面，支持编辑基本信息、目标、饮食偏好、授权、清空和返回聊天。
- 个人档案 API 复用现有 JWT 用户身份和用户隔离边界。

### 19.3 Workflow 与 Grill 接入

- `ConversationRuntime` 每轮加载当前用户已授权的个人档案。
- 已授权的健康目标和过敏信息以 `preference` 来源预填 Grill 字段。
- 用户本轮明确输入的值优先级高于档案偏好，不会被旧档案覆盖。
- `advice` 和普通问答不会因为个人档案被强制转成餐单任务。
- 未授权档案不会进入 Workflow 或模型上下文。

### 19.4 实际验收

```text
P2-1 专项测试：2 passed
P2-1 + 追问/安全/RAG/知识库回归：16 passed
全量非浏览器测试（临时内存 SQLite）：137 passed，1 skipped
0007 SQLite 迁移：通过
Ruff：通过
Mypy（P2-1 变更范围）：通过
真实浏览器：登录、填写并授权保存、刷新持久化、清空档案、刷新后确认授权撤回和字段清空，均通过
```

浏览器验收使用临时测试账户完成，测试凭据和档案内容未写入代码或实施文档。

### 19.5 当前边界

- 当前版本支持用户主动填写和修改档案，暂不自动从对话中提取并保存新偏好。
- 当前只提供个人档案，不引入多租户档案、企业 RBAC 或外部身份中心。
- BMI、热量和运动建议仍由现有工具和模型处理，不把个人档案升级为医疗诊断或处方系统。

## 20. P2-5：小型平台多租户基础能力实施记录

本阶段严格按照主线中的 `P2-5：小众平台多租户基础能力` 实施，目标是在保留 SQLite 默认路径的同时，为少量租户提供可验证的工作区隔离和基础角色能力。完整实现说明见 [P2-5 实施文档](p2-5-implementation.md)。

### 20.1 实际落地内容

- 新增 `tenants`、`tenant_memberships` 和 `tenant_settings`，并通过 `0008_multi_tenant` 迁移把会话、档案、记忆、反馈、幂等记录和知识库数据纳入租户边界。
- 新增 `core/tenant.py`，统一解析 `X-Tenant-ID`、检查成员关系和校验 `owner/admin/member` 角色。
- 默认创建确定性的个人租户，旧 SQLite 数据按用户回填，兼容原有单用户使用方式。
- 租户上下文贯通 ConversationRuntime、Workflow、Profile、Memory 和 Knowledge Base；索引目录按租户拆分。
- 租户级 Grill Profile、知识库访问组和模型别名接入运行链路；未设置模型别名时回退到全局模型配置。
- 新增租户、成员和设置管理 API，并完成非成员访问拒绝测试。

### 20.2 实际验收

```text
P2-5 专项测试：4 passed
全量非浏览器测试（Python 3.12 Docker）：141 passed，2 skipped
0001 -> 0008 SQLite 迁移：通过
Python 3.12 compileall：通过
```

本阶段明确不把以下内容写成已完成能力：跨进程持久化用量账本、严格配额扣减、租户数据导出、邀请邮件、企业 SSO 和复杂 RBAC。`usage_limit` 已保留租户设置契约，后续仅在真实小众平台需求出现时补充执行层。

## 21. P2-2：个人对话体验增强实施记录

本阶段严格按照主线中的 `P2-2：个人对话体验增强` 实施，目标是在个人使用和小众平台范围内改善会话历史、快捷入口、追问过程和档案建议体验。完整说明见 [P2-2 实施文档](p2-2-implementation.md)。

### 21.1 实际落地内容

- `core/persistence.py` 新增档案建议和用户体验设置的数据模型、读写方法；会话列表增加搜索、归档筛选、数量限制和重命名能力。
- 新增 `0009_p2_2_conversation_experience` 迁移，创建 `profile_suggestions` 和 `user_experience_settings`。
- `core/profile.py` 增加高置信、确定性的档案候选提取；候选不会自动保存，接受建议前必须通过个人档案授权门禁。
- 新增 `core/experience.py`，提供常用目标目录、回答显示设置和 Grill 操作请求模型。
- `core/grill_engine.py` 增加追问进度、跳过和修改操作；必填字段及安全关键字段保持不可跳过。
- `core/conversation_runtime.py` 将 Grill 进度、模型信息和档案建议纳入统一响应；前端增加历史搜索、重命名、快捷入口、进度和建议卡片。
- 修复回答结束后刷新历史列表导致当前响应卡片消失的问题；搜索和归档筛选不会清空当前已渲染回答。

### 21.2 实际验收

```text
P2-2 专项测试：4 passed
全量非浏览器测试（Python 3.12 Docker）：145 passed，2 skipped
0001 -> 0009 SQLite 迁移：通过
Python compileall：通过
浏览器对话验收：通过
```

浏览器验收使用临时测试账户，验证了减脂通用建议、制定餐食追问、进度更新、字段修改、会话重命名和搜索、档案建议授权门禁以及显示设置持久化。测试账户和令牌未写入代码或文档。

### 21.3 本阶段边界

- 档案建议只处理明确、高置信表达，不做低置信自动画像。
- 快捷入口不绕过 Intent Router、Workflow、Grill 和安全门禁。
- 不引入独立推荐服务、企业偏好中心、复杂画像模型或万人级协同能力。

## 22. P2-3：个人知识和回答质量实施记录

本阶段严格按照主线中的 `P2-3：个人知识和回答质量` 实施，目标是让个人用户可以导入自己的饮食笔记，并让回答在租户公共知识之外按用户边界检索个人知识；模型不可用时仍返回明确、可解释的离线回答。完整说明见 [P2-3 实施文档](p2-3-implementation.md)。

### 22.1 数据边界和迁移

- `KnowledgeDocumentRecord` 增加 `scope`、`owner_user_id` 和 `deleted_at`；知识构建记录、检索事件同步增加范围和所有者字段。
- 唯一约束从“租户 + 来源名”扩展为“租户 + scope + 所有者 + 来源名”，同一租户的不同用户可以拥有同名个人文档。
- 新增 `0010_p2_3_personal_knowledge.py`，并增强 SQLite 旧库兼容逻辑，支持已有数据库补齐新增字段。
- 个人索引按“租户 / 用户”拆分，个人文档不会进入租户公共索引；软删除后会重建对应个人索引。

### 22.2 个人知识服务和 API

- 新增 `core/personal_knowledge.py`，复用既有知识库生命周期、版本、同步构建和检索契约。
- 新增 `GET/POST/DELETE /me/knowledge/documents`、`GET /me/knowledge/index/status` 和 `POST /me/knowledge/retrieval/test`。
- 当前支持 UTF-8 `.txt`、`.md` 和粘贴文本；导入后自动构建并发布个人索引，删除使用软删除。
- 所有个人文档列表、详情、删除、索引构建和检索均同时校验 `tenant_id` 与 `owner_user_id`。

### 22.3 RAG、对话和离线回答

- `rag/ingestion.py` 和 `rag/retriever.py` 支持按租户公共范围、个人范围分别读取索引。
- 对话检索会按当前用户合并租户公共知识和个人知识，来源分别标记为 `knowledge_base` 与 `personal_knowledge`，并返回 scope、版本、片段和分数。
- 检索调试返回原始 query、改写 query、当前索引版本和未命中原因，便于定位“没有命中”还是“没有索引”。
- 新增 `core/offline_answer.py`，统一 `mode`、`reason`、`confidence` 和 `next_step` 契约；模型不可用或报错时明确显示“离线规则回答”，不伪造精确营养数字，也不会把通用减脂建议直接跳转成具体餐次餐单。
- `front/app.py` 的 API Key 模式在未传用户身份时使用已验证的 `service` 身份，兼容本地知识管理和个人知识页面的开发验收。

### 22.4 前端和实际验收

- 新增 `/me/knowledge` 页面和 `personal_knowledge.js`，支持粘贴文本、选择 TXT/Markdown、导入建索引、列表查看、删除和检索调试。
- 新增 `test_p2_3_personal_knowledge.py`，覆盖导入、用户隔离、同名来源、删除后不可检索、离线契约和 `0001 → 0010` 迁移。
- 新增 `test_p2_3_browser.py`，覆盖真实浏览器页面、导入、列表、个人来源命中和删除后的列表更新。

本阶段实际验收结果：

```text
P2-3 专项测试：4 passed
P1-6 + P2-5 回归：6 passed
全量非浏览器测试：149 passed，1 skipped，2 deselected
P1-6 + P2-3 浏览器回归：2 passed
JavaScript 语法检查：通过
Ruff 变更范围检查：通过
```

浏览器验收使用隔离端口和临时 SQLite 数据库，测试结束后已删除本轮生成的租户索引、隔离数据库和 uv 临时缓存；没有删除原有基础 `data/vector_store/index.faiss`。

### 22.5 本阶段边界

- 当前只支持文本/Markdown，不做 PDF、Office、网页抓取和对象存储解析。
- 当前使用本地 FAISS 和同步索引构建，不引入 Celery、队列、独立向量数据库或知识治理后台。
- 追问黄金集和营养事实来源仍需持续扩充，属于 P2-3 后续维护项；本阶段不把已有测试集数量包装成完整评测平台。
- 离线回答是安全可解释的降级路径，不等同于配置模型后的完整生成质量。

## 23. 当前已知边界

本记录只记录已经实际完成的 Grill Engine、P01、P02、P03、P04、P05、P0-8、P1-0～P1-6、P2-1～P2-3 和 P2-5，不把后续计划写成已完成能力。

当前仍有以下边界：

- JWT 用户认证、Refresh Token 轮换和 Redis 共享协调已在 P04 落地；完整 RBAC、企业 SSO/OIDC 和更完整审计留存仍未接入。
- CI 已增加自动检查，但 CD 发布、镜像签名、制品仓库和自动回滚仍需接入实际发布平台。
- Kubernetes 真实集群、Ingress Controller、Metrics Server、Prometheus Operator 和生产级 Redis/PostgreSQL 高可用尚未在本机验收。
- PostgreSQL 备份工具和恢复演练已完成；定时任务、对象存储、保留策略和生产级恢复演练仍需结合环境落地。
- TLS、告警、分布式链路追踪和更细粒度的数据访问策略仍需按生产环境补齐。
- 未配置模型 Key 时只能使用离线降级能力，不能获得完整的模型生成答案。

