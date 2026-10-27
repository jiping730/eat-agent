# P0-7 可观测性实施记录

本文档记录小型平台当前已经落地的日志、指标和链路追踪能力。P0-7 不新增独立观测服务，默认只依赖应用内 JSON 日志和 Prometheus `/metrics`；OpenTelemetry 与 Langfuse 作为可选外部集成。

## 1. 观测链路

一次请求使用同一组关联字段：

```text
HTTP request
  └─ request_id / trace_id
      └─ conversation.ask
          ├─ grill.check
          ├─ tool.execute
          │   └─ retrieval_tool / calorie_query / meal_planner / web_search
          ├─ rag.retrieve
          └─ llm.call
```

`request_id` 用于定位一次 HTTP 请求，`conversation_id` 用于定位会话，`trace_id` 用于关联整条链路。工具结果保留自己的 `trace_id`，审计日志同时记录 `tool_trace_id` 和 `parent_trace_id`。

## 2. JSON 日志

`core/logging_config.py` 统一输出 JSON。请求上下文会自动注入：

- `request_id`
- `trace_id`
- `conversation_id`
- `user_id_hash`
- `intent`

工具审计事件 `tool_execution` 还包括工具名、调用方、状态、错误码、尝试次数、耗时和来源数量。日志不会记录原始用户 ID、API Key、Token、Cookie、Authorization 或查询正文。

## 3. Prometheus 指标

指标定义位于 `core/observability.py`，标签保持低基数，不使用请求 ID、会话 ID、用户 ID 或原始查询作为标签。

| 类别 | 指标 |
| --- | --- |
| HTTP | `eat_agent_http_requests_total`、`eat_agent_http_request_duration_seconds` |
| Workflow | `eat_agent_workflow_runs_total`、`eat_agent_workflow_duration_seconds` |
| Grill | `eat_agent_grill_decisions_total`、`eat_agent_grill_rounds`、`eat_agent_grill_issues_total` |
| Tool | `eat_agent_tool_calls_total`、`eat_agent_tool_duration_seconds`、`eat_agent_tool_retries_total`、`eat_agent_tool_circuit_events_total` |
| LLM | `eat_agent_llm_requests_total`、`eat_agent_llm_duration_seconds`、`eat_agent_llm_tokens_total`、`eat_agent_llm_cost_total` |
| RAG | `eat_agent_rag_requests_total`、`eat_agent_rag_duration_seconds`、`eat_agent_rag_documents` |
| Fallback | `eat_agent_fallbacks_total` |

只有 provider 返回 usage 时才统计 token；没有 usage 时不会伪造 token 数或费用。费用按 `LLM_INPUT_COST_PER_1K` 和 `LLM_OUTPUT_COST_PER_1K` 估算。

## 4. 可选追踪与 LLM 观测

默认关闭外部 exporter：

```dotenv
OTEL_ENABLED=false
OTEL_SERVICE_NAME=eat-agent
OTEL_EXPORTER_OTLP_ENDPOINT=
LANGFUSE_ENABLED=false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=
LANGFUSE_CAPTURE_CONTENT=false
LLM_INPUT_COST_PER_1K=0
LLM_OUTPUT_COST_PER_1K=0
```

启用 OpenTelemetry 时安装项目的可选 observability 依赖，并设置 OTLP endpoint。启用 Langfuse 时提供密钥和地址。外部 SDK 不可用、初始化失败或 exporter 失败时，系统会 fail-open，继续使用本地 JSON 日志和 Prometheus 指标。

当前 Langfuse 只发送关联元数据、模型、结果和 token 统计，不发送对话正文；`LANGFUSE_CAPTURE_CONTENT` 默认关闭并保留为显式策略开关。

## 5. 告警

Prometheus 规则位于 `deploy/monitoring/prometheus-alerts.yml`，覆盖：

- HTTP 5xx 比例超过 5%
- Workflow P95 延迟超过 5 秒
- 工具失败率超过 20%
- 工具熔断打开
- LLM fallback 比例超过 10%
- readiness endpoint 持续返回非 200

阈值是小型平台的起始值，应结合实际流量和基线调整。规则本身不负责通知，通知由部署环境的 Alertmanager 或云监控系统配置。

## 6. 验收方式

```text
python -m pytest -q
GET /health/live
GET /health/ready
GET /metrics
```

Docker Compose 使用 `eat-agent:p07`。默认只验证 PostgreSQL、Redis、应用健康检查和 `/metrics`；没有配置 LLM Key 时，LLM 走安全 fallback，不应阻断浏览器多轮追问流程。

## 7. 当前边界

这是小型平台级可观测性，不包含独立 Jaeger、Tempo、Loki、Prometheus 集群、跨 Pod 共享熔断状态或多租户指标隔离。后续如果进入生产规模，再把 OTLP、日志采集、指标存储和告警通知交给平台基础设施承载。
