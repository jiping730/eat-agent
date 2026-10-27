# P1-2 实施记录：模型网关和模型路由

## 阶段目标

在小型平台范围内统一模型调用入口，支持智谱主模型、备用模型、有限重试、任务分流、Token/费用预算和调用审计，并保持无 API Key 时的离线降级能力。

## 实际实现

### 1. LiteLLM 网关

- `utils/llm.py` 新增 `ModelGateway`，通过 LiteLLM 的统一 `completion` 接口调用模型。
- 默认 Provider 是智谱 OpenAI-compatible API，调用模型自动转换为 `openai/<model>` 形式，并使用 `LLM_API_BASE` 和 `ZHIPUAI_API_KEY`。
- `GatewayLLM` 提供现有 Workflow 使用的 `.invoke()` 适配；`get_llm()` 已切换到网关。
- `CustomZhipuChat` 保留为历史兼容入口，旧调用方不需要一次性迁移。

### 2. 模型路由

- `intent` 任务默认使用 `LLM_INTENT_MODEL`，用于低置信度请求的补充分类。
- `answer` 任务默认使用 `LLM_ANSWER_MODEL`，未配置时回退到 `LLM_MODEL`。
- 通过 `LLM_FALLBACK_MODELS` 配置备用模型，例如 `glm-4-air,glm-4-flash`；主模型失败后按顺序尝试。
- 路由结果复用 `ModelRouteDecision`，包含 Provider、模型、主/备用路由、尝试次数和是否使用备用模型。

### 3. 超时、重试和降级

- 每次调用传递 `LLM_TIMEOUT_SECONDS`，最多执行 `LLM_MAX_ATTEMPTS` 次重试。
- 重试使用指数退避，失败后切换下一个模型候选。
- LiteLLM 未安装、Provider 未配置、调用失败或返回空内容时抛出安全网关错误，由现有 Workflow 进入离线回答逻辑。
- 不把底层异常、Prompt 或密钥返回给用户。

### 4. 意图和回答分流

- 原有高置信度规则路由保持不变，避免明确的“我想减肥”被模型改写为制定餐单。
- 低置信度请求且配置了模型 Key 时，调用 `intent` 模型输出严格 JSON，并使用 `RequestIntent` 校验。
- 模型输出非法、超出允许枚举或调用失败时自动回到确定性分类。
- 最终复杂回答使用 `answer` 路由，不与意图识别共用任务配置。

### 5. Token、费用和审计

- 新增 `InMemoryBudgetStore`，按 UTC 日期和用户指纹记录 Token/费用。
- 调用前预留预算，成功后按实际使用量结算，失败后释放预留。
- `LLM_USER_DAILY_TOKEN_LIMIT` 和 `LLM_USER_DAILY_COST_LIMIT` 为 0 时表示不限制；配置后超限请求在调用前被拒绝。
- Prometheus 和结构化日志记录任务、Provider、模型、路由、Token、费用、耗时、错误类型和 fallback 情况，不记录 Prompt、用户输入和用户明文 ID。

## 验收记录

- P1-2 专项及相关观测回归：`16 passed`。
- 覆盖主模型路由、低成本意图路由、备用模型切换、超时失败重试、预算拦截、非法意图输出回退和旧智谱适配器兼容。
- LiteLLM 已写入 `pyproject.toml` 和 `uv.lock`。

## 交付边界

预算账本和路由状态当前是进程内实现，适合小型平台单体部署；多 Worker/Pod 共享额度、在线 Provider 管理、复杂成本中心和独立模型服务暂缓到后续规模化阶段。未配置 Key 时仍使用既有离线降级，不会因为 LiteLLM 或模型服务不可用导致平台无法启动。
