# P2-2 实施记录：个人对话体验增强

## 阶段目标

在当前个人使用和小众平台范围内，让对话过程更容易管理、更容易理解，也让用户可以控制哪些信息进入个人档案。所有快捷入口仍然经过既有 Intent Router、Workflow 和 Grill，不绕过信息完整性检查。

## 实际实现

### 1. 会话历史管理

修改 `core/persistence.py`、`front/app.py` 和聊天前端：

- 支持按会话标题、会话 ID 和消息内容搜索。
- 支持排除已归档会话以及包含已归档会话的历史查看。
- 增加会话标题重命名接口和页面入口。
- 搜索、重命名和历史刷新继续使用 `tenant_id + user_id` 双重隔离。
- 修复即时回答后的历史刷新问题：刷新会话列表不会清掉当前回答中的追问进度、档案建议和模型信息卡片。

新增/扩展接口：

```text
GET   /conversations?q=&archived=&limit=
PATCH /conversations/{conversation_id}
```

### 2. 对话中的档案建议

新增 `ProfileSuggestionRecord`、`ProfileSuggestion` 和 `ProfileService` 建议流程：

- 从用户明确表达中提取高置信度候选，例如过敏/忌口、控制体重、增肌、每日餐数、素食和低碳饮食。
- 候选只生成“建议”，不会因为一句对话自动写入长期档案。
- 接受建议前必须已有个人档案授权；未授权时接口和页面都给出明确提示。
- 接受后复用现有 `ProfileService` 的校验、合并和字段审计机制。
- 建议按租户、用户、状态和过期时间隔离；默认保留待确认建议，支持保存、暂不保存和过期处理。

新增接口：

```text
GET  /me/profile/suggestions
POST /me/profile/suggestions/{suggestion_id}/accept
POST /me/profile/suggestions/{suggestion_id}/dismiss
```

同时补充了中文数字餐数识别，例如“每天三餐”。

### 3. 常用目标和回答显示设置

新增 `core/experience.py`：

- 提供减脂、增肌、均衡饮食、热量查询和制定餐食五个快捷入口。
- 快捷入口只填充用户意图，后续仍由原有 Workflow/Grill 决定是直接建议还是继续追问。
- 提供模型信息、来源、安全提示和回答风格设置。
- 设置按租户和用户保存，支持部分更新，不覆盖未修改的设置。

新增接口：

```text
GET /me/experience-settings
PUT /me/experience-settings
GET /me/shortcuts
```

### 4. Grill 追问体验

修改 `core/grill_engine.py` 和 `core/conversation_runtime.py`：

- `GrillContext` 增加已跳过字段记录。
- 增加追问进度计算：已完成字段、必填字段总数、当前字段、轮数和可否跳过。
- 增加跳过、修改和重新开始操作。
- 必填字段和安全关键字段不可跳过；修改字段会清理其旧值和相关依赖状态。
- 普通文本目标在满足明确答案条件时可以计入首轮进度，但请求性话术不会被误写入字段。
- 前端展示“已完成/必填总数”、当前追问字段以及修改入口；允许跳过时显示跳过按钮。

新增接口：

```text
POST /conversations/{conversation_id}/grill/actions
```

### 5. 持久化迁移

新增 `migrations/versions/0009_p2_2_conversation_experience.py`：

- `profile_suggestions`：档案候选、确认状态、来源会话、过期时间。
- `user_experience_settings`：用户在租户内的显示偏好和快捷入口设置。

已验证可以从 `0001` 连续迁移到 `0009`，并且 `0009` 是当前 head。

## 验收结果

```text
P2-2 专项测试：4 passed（首轮专项修复后纳入全量）
全量非浏览器测试（Python 3.12 Docker）：145 passed，2 skipped
0001 -> 0009 SQLite 迁移：通过
Python compileall（core/front/migrations）：通过
浏览器对话验收：通过
git diff --check：通过（仅有 Git 的换行符提示）
```

浏览器实际验证内容：

- 注册并登录临时测试账户。
- 点击“减脂建议”，得到通用建议，不会直接跳到具体餐次；页面显示模型信息和档案建议卡片。
- 重命名当前会话，并通过搜索框检索重命名后的会话。
- 点击“制定餐食”，看到 `0/2` 追问进度；选择晚餐后进度变为 `1/2`，并出现“修改餐次”入口。
- 使用“修改餐次”返回餐次追问。
- 未开启个人档案授权时点击建议保存，页面显示授权门禁提示。
- 关闭“显示模型信息”后刷新页面，设置仍保持关闭。

## 交付边界

- 不引入独立推荐服务、消息队列、WebSocket、复杂画像模型或企业级偏好中心。
- 档案建议采用确定性高置信规则，暂不把低置信模型推断自动转成档案建议。
- 快捷入口不替代 Grill；需要餐食规划时仍必须收集安全关键和必填信息。
- 历史消息详情当前保留原有轻量消息展示；新产生的回答会完整展示本阶段的进度、来源、安全和建议卡片。
- 本阶段不实现租户级计费、复杂配额、邀请体系或企业身份中心。

