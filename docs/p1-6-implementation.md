# P1-6 实施记录：知识库管理后台

## 阶段目标

在现有 `FastAPI + LangGraph + RAG + PostgreSQL/SQLite` 小型平台内，把知识库从“命令行入库”升级为可运营的文档管理闭环：上传、审核、版本、发布、下线、索引进度、检索验证、命中分析和回滚。

本阶段复用 P1-1 的确定性清洗、分块、混合召回和原子发布能力，不引入异步任务平台、独立知识库服务或多租户系统。

## 实际实现

### 1. 文档和版本治理

- 新增 `knowledge_documents`：记录文档名称、标题、状态、最新版本、已发布版本、访问组和审核信息。
- 新增 `knowledge_document_versions`：保存不可变文本快照、版本号、内容哈希和创建人。
- 支持 `.txt`、`.md` UTF-8 文本；限制大小为 `KNOWLEDGE_MAX_DOCUMENT_BYTES`，默认 1 MiB。
- 文档状态为：`draft`、`approved`、`rejected`、`published`、`unpublished`。
- 同一文件名再次上传时生成新版本并回到草稿；线上仍然使用旧的 `published_version`，直到新版本审核并发布。
- 文件名经过路径穿越和扩展名校验，访问组默认为 `public`。

### 2. 索引构建和回滚

- `rag/ingestion.py` 新增 `ingest_document_entries()`，从数据库审核内容构建版本化语料。
- `KnowledgeBaseService.build_index()` 复用 `manifest.json`、`corpus.json` 和 `current.json` 原子发布机制。
- 新增 `knowledge_builds`，记录构建任务 ID、索引版本、阶段、进度、文档数、分块数和失败原因。
- 发布过程包括：准备 → 收集审核内容 → 构建语料 → 原子切换 → 完成。
- 回滚可以传构建任务 ID 或索引版本，旧版本保留不删除。
- 当前同步执行构建；小型平台可直接看到最终状态，后续规模化再拆异步任务。

### 3. 管理 API

| 功能 | 接口 |
|---|---|
| 上传文档 | `POST /admin/knowledge/documents` |
| 文档列表 | `GET /admin/knowledge/documents` |
| 文档详情和版本 | `GET /admin/knowledge/documents/{id}` |
| 审核 | `POST /admin/knowledge/documents/{id}/review` |
| 发布 | `POST /admin/knowledge/documents/{id}/publish` |
| 下线 | `POST /admin/knowledge/documents/{id}/unpublish` |
| 构建索引 | `POST /admin/knowledge/index/build` |
| 构建历史 | `GET /admin/knowledge/index/builds` |
| 构建详情 | `GET /admin/knowledge/index/builds/{id}` |
| 索引回滚 | `POST /admin/knowledge/index/rollback` |
| 检索测试 | `POST /admin/knowledge/retrieval/test` |
| 命中分析 | `GET /admin/knowledge/analytics` |

管理权限复用现有认证链路：JWT 中包含 `admin` 或 `knowledge_admin` 角色时允许操作；服务 API Key 的 `service` 角色允许操作；也可以使用 `KNOWLEDGE_ADMIN_USER_IDS` 配置用户 ID 白名单。

### 4. 管理页面

新增 `/admin/knowledge` 页面，包含：

- 文档上传和草稿创建；
- 文档状态、版本和审核操作；
- 构建进度和历史版本；
- 选择历史索引并回滚；
- 输入问题查看检索来源和证据片段；
- 查询总数、命中率和高频文档分析。

页面复用现有 JWT 登录态，也支持输入服务 API Key；没有管理权限时 API 返回统一 403 错误。

## 测试和验收

新增 `test_p1_6_knowledge_base.py`，覆盖：

- 文档上传和版本递增；
- 审核通过和发布门禁；
- 新版本发布前保留旧线上版本；
- 索引发布和回滚；
- 文档下线；
- 检索测试和命中率统计。

实际结果：

```text
P1-6 专项测试：1 passed
P1-5 + P1-6 回归：7 passed
Ruff：通过
Mypy（变更范围）：通过
git diff --check：通过
```

当前主机的临时目录 ACL 会阻塞 `tempfile.mkstemp`，所以没有把当前环境中的真实索引写盘过程宣称为通过；P1-1 已有的 RAG 入库、原子发布和回滚测试继续作为底层实现依据，管理服务专项测试隔离验证了数据库生命周期和发布策略。

## 小型平台交付边界

- 不实现完整 RBAC、OIDC/企业 SSO、租户级知识库和对象存储。
- 不引入 Celery、Arq、Temporal 或独立索引服务。
- 不支持 PDF/Office 等复杂文档解析；后续可在异步任务阶段增加解析适配器。
- 当前知识库内容保存在 PostgreSQL/SQLite，索引文件保存在应用数据目录；生产高可用存储留到 P2。
