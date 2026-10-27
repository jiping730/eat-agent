# P0-7 实施记录：日志、监控与链路追踪

## 目标

在不引入独立观测集群的前提下，让小型平台可以回答三个问题：一次请求经过了哪些阶段、哪一步变慢或失败、失败是否触发了安全降级。

## 已实现

1. 在 `core/observability.py` 建立统一的 `contextvars` 观测上下文，包含 `request_id`、`trace_id`、`conversation_id`、用户指纹和 intent。
2. 在 `front/app.py` 生成/接收并回传 `X-Request-ID`、`X-Trace-ID`；提供受配置保护的 `/metrics`。
3. 在 `core/conversation_runtime.py` 建立 `conversation.ask` span，记录 Workflow、Grill 轮数、响应类型和 fallback。
4. 在 `core/workflow.py` 建立 Grill 和 LLM 阶段关联；工具上下文带上父级 trace；内部异常不再进入用户可见结果。
5. 在 `core/tool_registry.py` 将工具执行耗时、状态、错误码、重试、熔断和父子 trace 纳入统一观测；工具结果保持独立 trace，日志额外输出 `tool_trace_id`。
6. 在 `utils/llm.py` 从 SDK response 的 usage 安全读取输入/输出 token，只在真实 usage 存在时计费；没有 Key 时记录 `llm_unavailable` fallback。
7. 在 `rag/retriever.py` 记录检索耗时、命中、文档数和异常；查询正文不写入日志、指标或 span 属性。
8. 清理应用启动、记忆降级和性能装饰器的 `print()`，统一改为结构化事件。
9. 增加可选 OpenTelemetry/Langfuse 配置和 fail-open 处理，默认不采集对话正文。
10. 增加 `deploy/monitoring/prometheus-alerts.yml`，覆盖 HTTP 5xx、Workflow P95、工具失败/熔断、LLM fallback 和 readiness。
11. Compose/Helm 默认版本更新为 `eat-agent:p07` / `0.7.0`。

## 验证记录

- P0-7 专项测试：15 passed。
- 全量测试：90 passed，1 个既有 Starlette/httpx 弃用警告。
- Docker 镜像：`eat-agent:p07` 构建成功。
- Compose：PostgreSQL、Redis、应用均 healthy。
- 运行态：`/health/live`、`/health/ready` 返回 200，`/metrics` 暴露 P0-7 指标。
- 浏览器：完成“我想减肥 → 晚餐 → 没有”的三轮追问，得到最终餐食建议；刷新页面后对话仍可见。

## 交付边界

当前实现面向小型平台，未引入 Jaeger/Tempo/Loki 等独立服务，也未实现跨 Pod 共享熔断状态、多租户指标隔离或复杂采集平台。这些内容保留到平台规模扩大后再实施。
