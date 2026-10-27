# P1-0 实施记录：公共基础准备

## 阶段目标

在进入 RAG、模型网关、MCP 和流式功能开发前，先冻结跨模块数据契约，避免每个模块各自定义来源、模型路由和事件格式。

## 实际实现

- 新增 `core/contracts.py`，统一定义：
  - `SourceRef`、`RetrievedDocument`、`RetrievalResponse`：RAG 来源、文档和结果协议。
  - `ModelRouteRequest`、`ModelRouteDecision`：模型网关输入和路由审计协议。
  - `StreamEvent`：P1-4 SSE 事件协议，支持序号、请求关联和可回放序列化。
  - `McpToolContract`：MCP 工具版本、Schema 和调用方协议。
  - `EvalCase`：RAG 和端到端黄金用例协议。
- 所有契约默认禁止未知字段，限制字符串长度、Token、超时和温度范围，降低接口漂移和资源滥用风险。
- `StreamEvent.to_sse()` 固定浏览器 EventSource 所需的 `event/id/data` 格式。
- 在 `core.observability` 增加模型路由计数指标，不记录 Prompt、用户输入或用户身份明文。
- 新增 `test_p1_foundation.py`，覆盖来源、空检索结果、模型参数边界、SSE 序列化、MCP 和评测用例。

## 验收记录

- P1-0 专项测试：`5 passed`。
- P0 全量非浏览器回归：`108 passed, 1 skipped`。
- Python 3.12 编译检查、Ruff、Black、isort 和 Mypy 均通过。
- 新增 `core/contracts.py` 已纳入 CI 的 Black、isort 和 Mypy 检查范围。

## 交付边界

本阶段只冻结公共契约和观测基础，不接入 LiteLLM、不改造现有 FAISS 检索链路、不新增 SSE 接口、不注册 MCP Server，也不引入 Qdrant、任务队列或管理后台。上述能力分别在 P1-1 至 P1-5 中逐步接入。
