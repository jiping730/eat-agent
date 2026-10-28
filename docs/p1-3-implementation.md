# P1-3 实施记录：流式对话体验

## 阶段目标

在现有 `FastAPI + LangGraph + ConversationRuntime` 单体架构上，补齐小型平台需要的对话体验：回答可以逐步返回，用户能看到执行阶段，可以停止或重新生成回答，可以提交消息反馈，并能从历史会话恢复消息。

本阶段不引入 WebSocket、消息队列、Redis Stream、独立流式服务或并行多 Agent，继续沿用现有会话锁、幂等、持久化和用户隔离边界。

## 实际实现

### 1. SSE 事件契约和运行时

- 新增 `core/streaming.py`，提供 `StreamEmitter` 和 `StreamCancelled`。
- SSE 每个事件携带 `event`、连续 `sequence`、`request_id`、`conversation_id`、`trace_id`、时间戳和业务 `data`，便于前端消费和日志关联。
- `ConversationRuntime.ask_stream()` 使用后台线程和队列把现有同步 Workflow 转换为流式 HTTP 输出，同时复用原有会话锁、Redis 协调锁、幂等检查和最终持久化。
- `regenerate()` 会复用最近一轮已持久化的请求意图和 Grill 上下文，避免把“没有忌口”等字段回答误判成新的普通问答。
- 客户端断开或点击停止后设置取消事件；Workflow 节点和模型流式调用在安全检查点抛出 `StreamCancelled`，服务端返回可识别的 `cancelled` 事件，不把半成品写入正式回答。

### 2. Workflow 和模型增量输出

- Workflow 增加 `model.started`、`retrieval.started`、`retrieval.completed`、`tool.started`、`tool.completed`、`grill.clarify` 等阶段事件。
- `ModelGateway.stream()` 支持模型增量读取，发出 `model.delta`；首个增量输出前仍允许按 P1-2 规则重试或切换备用模型，已经输出内容后不再切换模型，避免回答前后不一致。
- `GatewayLLM.stream()` 保持 LangGraph 节点的适配方式不变；无模型 Key 时仍使用既有离线降级路径。
- 最终事件 `answer.completed` 返回完整 `ConversationResponse`，包含消息 ID；随后发送 `conversation.completed`。

### 3. HTTP API

- 新增 `POST /ask/stream`，返回 `text/event-stream`，保留 `/ask` 的同步兼容接口。
- 新增 `POST /conversations/{conversation_id}/regenerate`，针对最近一条用户消息重新执行回答，不重复保存用户消息。
- 新增 `POST /messages/{message_id}/feedback`，支持 `up` / `down` 反馈，并校验消息属于当前用户且为 assistant 消息。
- 会话详情返回消息 ID、请求 ID、响应类型和目标字段，支持前端历史恢复和消息操作。

### 4. 持久化和迁移

- `messages` 的保存结果返回 assistant 消息 ID；原有响应幂等记录在最终消息 ID 确定后同步更新。
- 新增 `message_feedback` 表和唯一约束 `(message_id, user_id)`，同一用户重复反馈采用更新语义。
- 新增 Alembic 迁移 `0004_streaming_feedback`，同时维护消息、会话外键和索引。
- 删除会话时同步删除反馈，避免遗留无主反馈记录。

### 5. 前端体验

- 使用 `fetch + ReadableStream` 解析 SSE，不新增前端框架或长连接基础设施。
- 对话气泡显示“正在理解”“正在检索”“正在整理”“正在生成”等阶段状态，并实时拼接模型增量文本。
- 发送按钮在生成期间变为“停止”，通过 `AbortController` 取消请求。
- 回答完成后显示重新生成、 有帮助、需改进操作；历史会话加载时恢复消息及其操作元数据。
- 增加登录身份守卫，未建立身份时不加载受保护的会话列表，避免前端启动阶段产生无意义的未授权请求。

## 验收范围

- `StreamEmitter` 序号连续、取消后不再发普通事件。
- 模型增量输出、预算结算、Workflow 流式持久化和最终消息 ID。
- 反馈保存、重新生成不重复用户消息、同步 `/ask` 兼容性。
- SSE 接口真实响应格式、浏览器流式交互、停止生成、重新生成、反馈和页面刷新后的历史恢复。
- Python 静态质量、前端 JavaScript 语法检查和 Docker Python 3.12 运行环境验收。

## 小型平台交付边界

本阶段的流式任务仍由应用进程内线程和队列承载，适合当前单体小型平台。多副本的流式连接接管、跨节点取消、断点续传、消息版本树、反馈分析后台和实时推送基础设施暂不纳入 P1-3；如后续并发和可靠性要求上升，再评估 Redis Stream、任务队列或 WebSocket。

## 验收记录

最终通过的测试数量和镜像标签以本轮交付检查结果为准，并同步写入总实施记录。
