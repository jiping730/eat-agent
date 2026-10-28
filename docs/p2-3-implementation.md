# P2-3：个人知识和回答质量实施文档

> 本阶段目标：让个人用户可以导入自己的饮食笔记，回答时按租户和用户边界参考这些内容；当模型不可用时，仍然返回明确、可解释的离线规则回答。
>
> 适用范围：个人长期使用和少量租户的小型平台。本文记录实际实现，不把企业级知识治理、异步任务平台或独立向量数据库列为当前交付内容。

## 1. 阶段结论

P2-3 已完成个人知识闭环并通过自动化和浏览器验收：

```text
导入 TXT/Markdown 或粘贴文本
  → 绑定当前租户和当前用户
  → 同步构建独立个人索引
  → 页面检索调试并返回来源证据
  → 对话检索合并租户公共知识与当前用户个人知识
  → 删除后软删除并重建个人索引
```

模型不可用时，回答会明确标记为离线规则回答，并返回原因、置信度和下一步建议；不会伪造模型已经生成了精确营养结论。

## 2. 实施范围

### 2.1 本阶段完成

- 个人知识文档的数据范围、所有者和软删除字段。
- 个人文档导入、列表、删除、索引状态和检索调试 API。
- 个人索引按租户和用户拆分。
- RAG 检索对租户公共知识和个人知识进行边界明确的合并。
- 对话来源中区分 `knowledge_base` 和 `personal_knowledge`。
- 模型不可用、模型异常和超时场景的统一离线回答契约。
- `/me/knowledge` 个人知识页面。
- Python 专项测试、迁移测试、浏览器流程测试和 JavaScript 语法检查。

### 2.2 明确不在本阶段

- PDF、Word、Excel、网页和图片 OCR 解析。
- 对象存储、异步任务队列、批量向量化服务。
- Qdrant、pgvector、独立 Reranker 或知识图谱平台。
- 企业级审批流、复杂 RBAC、知识版本协作和多人编辑。
- 把离线规则回答包装成完整模型回答。

## 3. 数据模型和迁移

### 3.1 数据边界

`knowledge_documents`、`knowledge_builds` 和 `knowledge_retrieval_events` 均使用以下边界字段：

| 字段 | 用途 |
|---|---|
| `tenant_id` | 当前租户/工作区边界 |
| `scope` | `tenant` 表示租户公共知识，`personal` 表示个人知识 |
| `owner_user_id` | 个人知识的所有者；租户公共知识为空 |
| `deleted_at` | 个人知识软删除时间 |

个人文档的唯一范围是：

```text
tenant_id + scope=personal + owner_user_id + source_name
```

因此同一租户的两个用户可以分别导入同名 `notes.md`，互相看不到对方的文档和检索结果。

### 3.2 迁移

新增迁移文件：

```text
migrations/versions/0010_p2_3_personal_knowledge.py
```

迁移测试验证了从 `0001` 到 `0010` 的连续升级。SQLite 旧数据库兼容逻辑会为新增非空字段补充安全默认值，避免本地个人数据因为升级失败而无法启动。

## 4. 后端服务和 API

### 4.1 服务层

新增 `core/personal_knowledge.py`，作为个人入口服务。它复用 `KnowledgeBaseService` 的文档版本、索引构建和检索契约，但固定使用：

```text
scope = personal
access_group = personal
owner_user_id = 当前用户
```

个人导入采用同步流程：先写文档和版本，再构建当前用户的个人索引，最后返回文档和构建结果。

### 4.2 API

| 方法 | 路径 | 功能 |
|---|---|---|
| `GET` | `/me/knowledge/documents` | 列出当前用户个人文档 |
| `POST` | `/me/knowledge/documents` | 导入文本并构建个人索引 |
| `DELETE` | `/me/knowledge/documents/{document_id}` | 软删除个人文档并重建索引 |
| `GET` | `/me/knowledge/index/status` | 查看当前用户个人索引状态 |
| `POST` | `/me/knowledge/retrieval/test` | 调试当前用户个人知识检索 |

导入接口支持 `.txt`、`.md` 文件名和纯文本内容；内容大小和文件名规则沿用知识库管理边界，拒绝路径穿越和不支持的扩展名。

### 4.3 软删除行为

删除不会直接物理清除文档版本，而是：

1. 设置 `deleted_at` 和 `status=deleted`。
2. 列表和检索查询过滤已删除文档。
3. 重建当前用户的个人索引。
4. 返回新的索引构建结果。

这样可以保留本地数据库的可追溯性，同时保证删除后不能继续检索到文档内容。

## 5. RAG 和对话接入

### 5.1 索引目录

个人索引的逻辑目录为：

```text
data/vector_store/tenants/{tenant_id}/personal/{owner_user_id}/
```

租户公共知识仍使用租户目录，不与个人目录混用。当前采用本地 FAISS 和同步版本发布，符合小型平台的数据规模和单机部署边界。

### 5.2 检索结果

个人检索调试返回以下信息：

- 原始 query。
- 查询改写后的 query。
- 当前 active index version。
- `status` 和未命中原因。
- 命中文档、来源、scope、版本、片段和分数。

对话检索在当前用户存在个人文档时，会合并：

```text
当前租户公共知识
      +
当前租户 / 当前用户个人知识
```

个人来源使用 `personal_knowledge` 标识，租户公共来源使用 `knowledge_base` 标识，前端可以据此展示来源范围。

## 6. 离线回答契约

新增 `core/offline_answer.py`，统一离线回答结果：

```json
{
  "mode": "offline",
  "reason": "llm_unavailable",
  "confidence": "medium",
  "next_step": "配置模型后可获得更完整的个性化回答。"
}
```

当前覆盖：

- `llm_unavailable`：未配置可用模型。
- `llm_error`：模型调用失败。
- `timeout`：模型调用超时。

离线回答保留通用、低风险的减脂和饮食建议，但不会生成缺少来源的精确营养数字；回答区域会显示“离线规则回答”。这也避免“我想减肥”在没有明确餐次时被错误推进到具体餐食规划。

## 7. 前端页面

新增：

```text
front/templates/personal_knowledge.html
front/static/personal_knowledge.js
```

入口：

```text
/me/knowledge
```

页面支持：

- 粘贴文本或选择 TXT/Markdown 文件。
- 输入标题并导入。
- 查看当前用户个人文档、状态、版本和更新时间。
- 删除文档。
- 输入查询并查看个人知识命中来源、片段和版本。

本地 API Key 兼容模式从 `localStorage.knowledgeApiKey` 读取服务 Key；实际 JWT 用户模式仍以已验证 Token 的用户身份为准。

## 8. 测试和验收

### 8.1 自动化测试

新增：

```text
test_p2_3_personal_knowledge.py
test_p2_3_browser.py
```

专项覆盖：

- 个人文档导入和索引发布。
- 同租户不同用户隔离。
- 同一用户同名来源更新。
- 删除后列表和检索均不可见。
- 离线回答结构化契约。
- `0001 → 0010` 迁移。
- 浏览器导入、列表、检索命中和删除。

最终验收结果：

```text
P2-3 专项测试：4 passed
P1-6 + P2-5 回归：6 passed
全量非浏览器测试：149 passed，1 skipped，2 deselected
P1-6 + P2-3 浏览器回归：2 passed
JavaScript 语法检查：通过
Ruff 变更范围检查：通过
```

浏览器测试使用隔离端口和临时 SQLite 数据库；验收结束后删除了本轮生成的索引目录、临时数据库和 uv 缓存，保留原有基础索引文件。

## 9. 交付边界和下一步

P2-3 的个人知识基础闭环可以交付。剩余事项不阻塞本阶段使用：

- 持续扩充追问黄金集和回答回归集。
- 持续补充常见营养问题的可靠事实来源。
- 下一主线阶段是 P2-4：SQLite/知识库/档案/会话的本地备份恢复、升级检查和运行目录清理。

在进入 UI 统一优化前，优先完成数据备份恢复和升级安全性，避免后续页面改造时缺少可恢复的数据基线。
