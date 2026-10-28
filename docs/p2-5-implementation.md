# P2-5 实施记录：小型平台多租户基础能力

## 阶段目标

在不引入企业 SSO、复杂 RBAC、独立 IAM 或微服务的前提下，为个人使用和少量租户的小型平台增加工作区隔离能力。默认仍使用 SQLite，PostgreSQL 作为可选数据库；Redis 只作为已有多进程协调能力，不成为多租户数据的唯一存储。

## 实际实现

### 1. 租户数据模型与迁移

新增 `migrations/versions/0008_multi_tenant.py`，落地：

- `tenants`：租户/工作区基本信息、slug、状态和所有者。
- `tenant_memberships`：用户在租户内的成员关系和角色。
- `tenant_settings`：租户级模型别名、Grill Profile 覆盖、知识库访问组和轻量配置。
- 为会话、反馈、幂等记录、记忆、用户档案、知识库文档/版本/构建/检索事件增加 `tenant_id`。
- 知识文档源名称的唯一性收敛为“同一租户内唯一”，不同租户可以使用相同文件名。

迁移兼容策略：

- 已验证可以从 `0001` 连续迁移到 `0008`。
- SQLite 本地旧数据库启动时会补齐新增 nullable 列。
- 旧数据按用户回填到确定性的个人租户，避免升级后出现无归属数据。
- 个人租户创建使用进程内锁和幂等重试，降低并发首次访问时重复初始化的风险。

### 2. 成员关系与基础角色

新增 `core/tenant.py`，统一处理当前租户解析和权限校验：

- 默认每个用户拥有一个个人租户，兼容原有单用户使用方式。
- 支持 `owner`、`admin`、`member` 三种角色。
- `owner/admin` 可以管理租户设置和成员，`owner` 才能停用租户。
- 所有通过 `X-Tenant-ID` 选择的租户都要在服务端重新校验成员关系，不能信任前端传入的租户 ID。
- 非成员访问、已停用租户访问和角色不足会被拒绝，不会继续进入 Workflow 或数据查询。

### 3. 管理 API

新增接口：

```text
GET    /me/tenants
POST   /tenants
GET    /tenants/{tenant_id}
PUT    /tenants/{tenant_id}
DELETE /tenants/{tenant_id}

POST   /tenants/{tenant_id}/members
PUT    /tenants/{tenant_id}/members/{user_id}
DELETE /tenants/{tenant_id}/members/{user_id}

GET    /tenants/{tenant_id}/settings
PUT    /tenants/{tenant_id}/settings
```

接口继续复用现有 JWT/API Key 身份边界。租户选择使用 `X-Tenant-ID`，不传时自动使用用户的个人租户。

### 4. 运行时隔离

租户上下文已贯通 `ConversationRuntime` 和 LangGraph Workflow：

- 会话、消息、反馈、幂等记录按租户和用户共同过滤。
- 个人档案、记忆授权、记忆内容按租户隔离；同一用户在不同租户拥有不同档案和记忆空间。
- 知识库文档生命周期、构建记录、检索事件和访问组按租户隔离。
- 本地知识库索引目录按租户拆分：`data/vector_store/tenants/{tenant_id}/`。
- 租户的 `grill_profile` 会覆盖对应任务的默认 Grill Profile；`knowledge_scope` 会进入检索访问组过滤。
- `model_alias` 已接入统一 Model Gateway；未配置时继续使用全局模型配置。

### 5. 交付边界

本阶段提供的是小型平台的基础租户能力，不是万人级多租户平台：

- `usage_limit` 已有租户设置字段和 API 契约，但当前不实现跨进程持久化用量账本、计费和严格配额扣减。
- 现有请求限流仍以应用层限流为主，不建设独立配额中心。
- 不引入 OIDC/企业 SSO、复杂 RBAC、邀请邮件、组织层级、跨区域容灾或租户级独立服务。
- 租户删除采用停用语义，保留数据以避免误删；数据清理和导出可作为后续 P2-4/P2-5 补充。

## 验收结果

```text
P2-5 专项测试：4 passed
全量非浏览器测试（Python 3.12 Docker）：141 passed，2 skipped
0001 -> 0008 SQLite 迁移：通过
Python 3.12 compileall：通过
git diff --check：通过
```

专项测试覆盖：

- owner/admin/member 角色和跨租户成员拒绝。
- 会话、用户档案和记忆的租户隔离。
- 不同租户允许使用相同知识文档源名称，内容和索引互不串用。
- 租户模型别名实际传入 Model Gateway。

## 后续建议

P2-5 基础能力可以交付。后续若确实需要小众平台的运营能力，再单独增加租户用量日报、配额提示、数据导出和邀请流程；这些内容不应阻塞当前的个人使用和基础租户隔离。
