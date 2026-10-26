# 项目实施记录

> 本文记录已经实际完成并提交到 Git 的工作，不是未来规划清单。

## 1. 记录范围

本阶段围绕“用户信息不足时，Agent 自动追问，直到信息足够再回答”的目标完成了三项工作：

| 阶段 | 实际定位 | Git 提交 | 状态 |
|---|---|---|---|
| Grill Engine | 实现信息完整性检查和多轮追问 | `0689322` | 已完成 |
| P01 | 统一 Web、CLI、旧 Agent、MCP 的 Agent 执行架构 | `9a3b88a` | 已完成 |
| P02 | 完成配置、依赖、Docker、离线降级和运行验收 | `d232d9c` | 已完成 |

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

## 5. 实际验收记录

### 5.1 自动化测试

在 Linux Docker 生产镜像环境内执行：

```text
14 passed in 0.79s
```

测试覆盖了：

- Grill 首轮追问。
- 多轮字段收集。
- 关键字段缺失处理。
- 默认值处理。
- 最大追问次数和降级。
- 新意图切换。
- 会话运行时和统一架构契约。

### 5.2 API 验收

使用同一个 `user_id` 调用 `/ask`：

```text
我想减肥 → 追问餐次
晚餐 → 追问过敏原
没有 → 进入最终回答路径
```

首页 `GET /` 返回 HTTP 200，`POST /ask` 返回 HTTP 200。

### 5.3 浏览器验收

在真实浏览器页面中完成：

1. 输入“我想减肥”。
2. 页面显示“早餐、午餐、晚餐”候选按钮。
3. 点击“晚餐”。
4. 页面显示过敏原追问。
5. 点击“没有过敏或忌口”。
6. 页面显示“已完成回答”。

### 5.4 代码和交付检查

- `git diff --check` 通过。
- 工作区提交完成。
- 最新提交为 `d232d9c`。
- 最新 Docker 容器保持运行。

## 6. 当前已知边界

本记录只记录已经完成的 P01/P02，不把后续计划写成已完成能力。

当前仍有以下边界：

- 会话主要保存在进程内存中，服务重启后不会自动恢复。
- 当前没有用户认证、权限和限流系统。
- 生产环境还应使用 Gunicorn 等正式 WSGI 服务器。
- 还没有完整的 CI/CD、监控、告警和链路追踪。
- 未配置模型 Key 时只能使用离线降级能力，不能获得完整的模型生成答案。

