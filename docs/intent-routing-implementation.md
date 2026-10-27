# P0-8 实施记录：领域与操作模式路由

## 背景

旧路由把“减肥、减脂、增肌”等目标词直接映射为 `meal_planner`。因此用户仅表达目标时，系统会立刻进入餐单 Grill，并追问“哪一餐”。这会把“想获得建议”和“想制定具体餐单”混为一谈。

本阶段按小型平台主线引入统一的请求路由：先判断领域和操作模式，再判断是否需要任务 Profile 与 Grill。

## 路由模型

请求统一表示为：

```text
domain     领域，例如 nutrition、general
operation  操作，例如 advice、plan、lookup、calculate、execute、answer
goal       用户目标，例如 weight_control、improve_language
entities   业务实体
slots      已识别的结构化参数
task       兼容现有工具的任务名，例如 meal_planner、calorie_query
```

核心规则：

| 用户表达 | 路由 | 是否进入 Grill |
| --- | --- | --- |
| 我想减肥、怎么减脂 | `nutrition + advice` | 否 |
| 帮我安排减脂晚餐 | `nutrition + plan + meal_planner` | 是 |
| 鸡胸肉多少热量 | `nutrition + lookup + calorie_query` | 是 |
| 计算我今天摄入多少热量 | `nutrition + calculate + calorie_query` | 是 |
| 我想提高英语 | `general + advice` | 否 |
| 帮我制定英语学习计划 | `general + plan` | 当前无专用 Profile，给通用方案或说明边界 |

只有 `plan`、`lookup`、`calculate` 等确实需要结构化参数的操作才允许 Grill 追问。用户回答上一轮字段时，如果没有新的明确操作，则沿用上一任务；出现新的明确操作时切换任务。

## 实际修改

1. 新增 `core/intent_router.py`，使用确定性规则生成 `RequestIntent`，避免为每条消息增加一次模型调用，并统一识别领域、操作、目标、实体、槽位和跨轮延续状态。
2. `core/workflow.py` 接入新路由：
   - 建议/普通回答直接生成答案，不调用餐单 Grill。
   - 计划、热量查询和计算继续进入对应 Profile。
   - 保留 `current_goal` 作为工具、指标和持久化兼容字段。
   - 将结构化请求意图和操作模式写入现有 `grill_context`，不增加数据库迁移。
3. `core/grill_engine.py` 增加 `OperationSpec` 和 `advise` 动作，Profile 可以按操作配置是否需要 Grill 及其必填字段。
4. `meal_planner` 配置：
   - `advice` 不需要 Grill。
   - `plan` 需要 `meal_type`、`allergy_info`。
5. `calorie_query` 配置：
   - `lookup` 和 `calculate` 需要 `food`。
6. `core/conversation_runtime.py` 增加 `advice` 响应类型映射，并从已持久化的 `grill_context` 恢复操作模式。
7. LLM 不可用时补充建议型 fallback，避免 advice 被错误降级为餐单或热量工具错误。

## 验收记录

- 意图路由与 Grill 操作策略测试：9 passed。
- 既有 Grill、P0 架构、P0-3 持久化及 P0-5 兼容测试与新增路由测试合计：77 passed。
- 工作流集成测试：1 passed。
- 全量回归测试：99 passed，仅有既有 Starlette/httpx 弃用警告。
- Compose 运行态：PostgreSQL、Redis、应用均 healthy；`/healthz`、`/health/live`、`/health/ready`、`/metrics` 均返回成功。
- 浏览器对话测试通过：目标建议、明确餐单规划、补充忌口、刷新恢复均符合预期。
- 工作流集成验证：
  - `我想减肥` 返回建议，不返回 `target_field=meal_type`，不执行工具。
  - `那帮我安排晚餐` 进入 `meal_planner + plan`，追问忌口。
  - `没有忌口` 延续上一任务并执行餐单工具。

## 交付边界

当前实现目标是小型平台：路由规则可解释、可测试、可持久化，并为后续增加领域 Profile 保留扩展点。复杂多意图编排、独立策略服务和大规模模型路由暂不在本阶段范围内。
