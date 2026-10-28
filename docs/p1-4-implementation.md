# P1-4 实施记录：MCP 工具网关

## 阶段目标

在小型平台单体架构内，将本地 MCP Server 接入主 Workflow。MCP 工具与本地工具经过同一个 Tool Registry，统一执行权限、Schema 校验、超时、重试、熔断、来源和审计。

本阶段采用配置驱动的本地 stdio MCP，不引入独立 MCP 网关服务、数据库注册中心、远程服务发现、跨节点 Session 或 MCP 管理后台。

## 实际实现

### 1. MCP 契约和配置

- `core/contracts.py` 新增 `McpServerConfig` 和 `McpCallRequest`，扩展 `McpToolContract` 的版本、Schema 和调用方约束。
- `config.py` 增加 MCP Server 名称、允许暴露工具、Server JSON 配置和启动超时配置。
- `.env.example` 和 `docker-compose.yml` 增加对应配置入口，真实密钥仍只放在本地 `.env` 或部署环境中。

### 2. Server 注册和客户端生命周期

- 新增 `core/mcp_gateway.py`，实现 `McpServerRegistry`。
- 默认注册 `nutrition_local`，使用当前 Python 进程启动 `python -m mcp_servers.local_server`。
- 注册中心通过 MCP Client 完成初始化、工具发现、版本记录和 Session 生命周期管理。
- 每个 stdio Server 使用独立事件循环线程，保持同步 Workflow 与 MCP 异步协议之间的边界。
- MCP 依赖延迟加载；未安装 MCP 依赖时，应用仍能启动并回退到本地 Tool Registry。

### 3. 统一 Tool Gateway

- 新增 `McpToolGateway`，将发现到的 MCP 工具转换为现有 `ToolSpec`。
- 已存在的逻辑工具名（如 `calorie_query`、`meal_planner`）由 MCP 实现替换，Workflow 无需改变工具计划协议。
- 其他 MCP 工具使用 `{server_name}.{tool_name}` 命名，避免 Server 之间发生冲突。
- MCP 参数从 Grill 的 `fields` 和上下文中构造，兼容原有本地工具输入结构。
- MCP 返回结果统一转换为 `ToolResult`，并增加 MCP Server 和工具来源信息。

### 4. 权限、可靠性和安全边界

- 本地 MCP Server 只暴露 `MCP_LOCAL_ALLOWED_TOOLS` 中的工具。
- 工具仍由 Tool Registry 检查调用方和意图权限，禁止任意 MCP 工具调用。
- 输入 Schema 在调用前校验；MCP 输出 Schema 在网关返回前校验。
- MCP 调用复用 Tool Registry 的超时、重试和熔断机制。
- stdio Server 的日志改写到 stderr，避免污染 MCP JSON-RPC stdout 通道。
- MCP 失败只返回统一错误码，不向用户暴露 Python 异常堆栈。

### 5. Workflow 接入

- `ConversationRuntime` 的标准应用运行时自动加载 MCP Gateway。
- MCP 不可用时保留本地工具回退，不阻断服务启动。
- 主 Workflow 继续通过 `ToolRegistry.execute_result()` 执行，保留 P0-6 的统一审计和 P1-3 的 `tool.started` / `tool.completed` 流式事件。

## 验收范围

- Server 注册、重复名称检查和工具发现。
- MCP 工具名称冲突和逻辑名称兼容。
- 输入 Schema、输出 Schema、调用方权限和工具白名单。
- MCP 调用超时、异常和不可用回退。
- MCP 工具经过统一 Tool Registry 执行并产生审计日志。
- stdio JSON-RPC 通道不被应用日志污染。
- 主 Workflow 的本地营养工具实际走 MCP Client。
- 现有 `/ask`、`/ask/stream`、Grill 追问和浏览器流程不回归。

## 小型平台交付边界

本阶段的注册中心和 Session 管理均在应用进程内完成，适合当前单体小型平台。后续只有在需要远程 MCP 集群、多副本 Session 接管或在线工具管理时，才评估 Redis、独立网关服务或数据库注册中心。

