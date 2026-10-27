# 项目实施主线与优先级清单

> 本文是当前项目后续开发的唯一主线基线，依据用户确认的项目清单整理。
>
> 后续开发必须严格按本文的优先级和阶段顺序推进。已完成的历史阶段记录见 [implementation-record.md](implementation-record.md)，历史记录不能替代本文主线。

## 1. 总体技术主线

最终技术方向收敛为：

```text
FastAPI
  + LangGraph
  + Grill 追问引擎
  + PostgreSQL
  + Redis
  + pgvector / Qdrant
  + LiteLLM
  + Langfuse / OpenTelemetry
```

当前的 ReAct、旧 Skill、MCP、GraphRAG 都作为能力接入，不再各自发展成独立 Agent 主链路。

## 2. P0：必须优先完成

P0 未完成前，不继续堆叠新的 AI 能力。

### P0-1：统一 Agent 架构

目标：整个项目只有一条核心执行链路。

待实现：

- [x] 统一 CLI 和 Web 都调用 LangGraph Workflow
- [x] 将 `main.py` 从旧 ReAct Agent 迁移到统一 Workflow
- [x] 将 `agent_executor.py` 降级为兼容适配器，不再创建第二套 Agent
- [x] 统一 `core/skills`、`agent/tools.py`、`mcp_servers` 的工具实现边界
- [x] 建立统一 Tool Registry
- [x] 收敛重复的联网搜索实现到 Registry
- [x] 统一工具错误格式和返回格式
- [x] Grill 成为所有任务执行前的统一前置节点

验收标准：CLI、Web、未来 API 调用同一个 Workflow；同一个问题得到相同的意图、追问和工具执行结果。

### P0-2：补齐项目运行基础

目标：任何开发者都能从干净环境启动项目。

待实现：

- [x] 统一 `pyproject.toml` 和 `requirements.txt` 的依赖入口
- [x] 使用 `uv.lock` 锁定开发环境依赖
- [x] 拆分生产依赖和开发依赖
- [x] 增加 `.env.example`
- [x] 启动时校验必需配置
- [x] 可选服务没有配置时不能阻断主流程
- [x] 修复 FastAPI、LangGraph、pytest 等依赖声明不完整问题
- [x] 增加 Dockerfile
- [x] 增加本地 Docker Compose

验收标准：`uv sync`、`uv run pytest`、`uv run python -m front.app` 能够在干净环境完成安装、测试和启动。

### P0-3：会话和状态持久化

目标：服务重启、多进程部署后，用户对话仍然可靠。

待实现：

- [ ] 官方 LangGraph PostgreSQL Checkpointer（P2，当前使用自定义 SQLAlchemy 会话存储）
- [x] 将 `user_histories` 从内存迁移到数据库
- [x] 增加 `conversation_id`
- [ ] 增加 `tenant_id`（P2）
- [x] 增加会话过期时间
- [x] 支持会话归档和永久删除
- [x] 使用 Redis 保存跨 worker 的协调状态
- [x] 增加分布式锁，避免同一会话并发写入
- [x] 保证不同用户无法读取彼此会话

验收标准：服务重启后追问状态不丢失；两个用户使用相同消息不会互相污染；多进程部署后会话仍然一致。

### P0-4：API 安全和接口规范

目标：从 Demo API 升级为可对外提供服务的 API。

待实现：

- [x] Flask 迁移到 FastAPI
- [x] 使用 Pydantic 定义 Request/Response Schema
- [x] 增加用户认证（JWT/API Key，开发模式保留兼容身份头）
- [x] 增加 JWT；OIDC/企业 SSO 暂缓到 P2
- [x] JWT 模式下不信任前端传入的 `user_id`
- [ ] 增加租户权限校验（P2）
- [x] 增加请求限流
- [x] 增加最大输入长度和请求体限制
- [ ] 增加独立的 Workflow 超时控制
- [x] 增加幂等请求 ID
- [x] 将 CORS 改为可配置策略
- [x] 增加 `/health/live`
- [x] 增加 `/health/ready`
- [x] 统一错误码

验收标准：未登录用户不能访问业务接口；用户 A 不能访问用户 B 的会话；超长输入、非法 JSON、重复请求均有明确响应。

### P0-5：Grill v1 产品化

目标：让 Grill 成为稳定、可配置、可扩展的业务规则引擎。

实现清单：

- [x] 将 Task Profile 配置化
- [x] 支持字段类型：枚举、数字、日期、自由文本、布尔值
- [x] 支持字段校验器
- [x] 支持字段依赖关系
- [x] 支持字段冲突检测
- [x] 支持字段置信度
- [x] 支持用户拒绝回答
- [x] 支持用户中途换题
- [x] 支持多任务输入（小型平台采用顺序任务队列）
- [x] 支持追问确认
- [x] 支持 Profile 版本
- [ ] 支持按租户加载不同 Profile（P2；本阶段只保留扩展点）
- [x] 统一 Grill JSON 输出协议

推荐输出：

```json
{
  "action": "clarify",
  "task": "meal_planner",
  "target_field": "allergy_info",
  "question": "你有需要避开的食物或过敏原吗？",
  "missing_fields": ["allergy_info"],
  "confidence": 0.98
}
```

验收标准：

- [x] 关键字段缺失时绝不执行工具
- [x] 用户补充信息后可继续原任务
- [x] 用户明确换题时清理旧上下文
- [x] 连续追问超过限制后进入可解释 fallback
- [x] 准备 30～50 条黄金对话测试集（34 条）

### P0-6：工具执行可靠性

目标：工具可控、可重试、可审计。

待实现：

- [x] 所有工具注册到统一 Tool Registry
- [x] 为工具定义输入 JSON Schema
- [x] 为工具定义输出 JSON Schema
- [x] 增加工具超时
- [x] 增加重试和指数退避
- [x] 增加熔断
- [x] 增加工具权限白名单
- [x] 禁止任意工具执行
- [x] 工具调用记录到审计日志
- [x] 工具异常不直接暴露 Python 堆栈
- [x] 工具返回结果必须携带来源和状态

推荐工具返回结构：

```json
{
  "status": "success",
  "data": {},
  "sources": [],
  "error_code": null,
  "trace_id": "..."
}
```

### P0-7：日志、监控和链路追踪

目标：线上出问题时能定位，而不是依赖 `print()`。

待实现：

- [ ] 使用结构化 JSON 日志
- [ ] 增加 `request_id`
- [ ] 增加 `conversation_id`
- [ ] 增加 `trace_id`
- [ ] 记录 Grill 追问轮数
- [ ] 记录意图识别结果
- [ ] 记录工具耗时
- [ ] 记录 LLM 延迟
- [ ] 记录 Token 和费用
- [ ] 记录 RAG 命中情况
- [ ] 记录 fallback 率
- [ ] 增加错误告警
- [ ] 接入 OpenTelemetry
- [ ] 接入 Langfuse

重点指标：P50/P95/P99 响应时间、追问成功率、最终解决率、错误追问率、工具失败率、RAG 命中率、LLM 成本、会话中断率。

### P0-8：测试和 CI

目标：每次修改都能自动发现回归。

待实现：

- [ ] Grill 单元测试
- [ ] Workflow 集成测试
- [ ] API 测试
- [ ] 多轮会话测试
- [ ] 多用户隔离测试
- [ ] 工具失败测试
- [ ] LLM 超时测试
- [ ] RAG 无结果测试
- [ ] 浏览器 E2E 测试
- [ ] Prompt Injection 测试
- [ ] 并发测试
- [ ] pytest-cov
- [ ] Ruff
- [ ] Mypy
- [ ] GitHub Actions
- [ ] Pull Request 自动检查

最低门槛：单元测试覆盖率 ≥ 80%，核心 Workflow 覆盖率 ≥ 90%，所有 P0 场景必须有 E2E 测试。

## 3. P1：核心能力增强

P0 完成后再做 P1。

### P1-1：升级 RAG 检索质量

- [ ] 文档入库 CLI
- [ ] 文档清洗和去重
- [ ] 文档元数据
- [ ] 文档版本
- [ ] BM25 + 向量混合检索
- [ ] Reranker
- [ ] 查询改写
- [ ] 多路召回
- [ ] 权限过滤
- [ ] 返回来源和证据片段
- [ ] 索引原子发布和回滚
- [ ] RAG 评测集

技术选择：开发环境 FAISS；生产环境 PostgreSQL + pgvector 或 Qdrant；排序使用 BGE Reranker / Cohere Rerank。

### P1-2：模型网关和模型路由

- [ ] 接入 LiteLLM
- [ ] 智谱模型作为主模型
- [ ] 配置备用模型
- [ ] LLM 超时和重试
- [ ] 低成本模型处理意图识别
- [ ] 高能力模型处理复杂回答
- [ ] Token 预算
- [ ] 单用户费用限制
- [ ] 模型调用审计

### P1-3：流式对话体验

- [ ] SSE 流式输出
- [ ] 展示当前执行阶段
- [ ] 展示“正在检索”“正在整理”等状态
- [ ] 支持停止生成
- [ ] 支持重新生成
- [ ] 支持消息反馈
- [ ] 支持会话历史页面

### P1-4：MCP 工具网关

- [ ] MCP Server 注册中心
- [ ] MCP 工具权限策略
- [ ] 工具版本管理
- [ ] 工具超时和熔断
- [ ] MCP 调用审计
- [ ] 工具输入输出 Schema 校验
- [ ] 将本地 MCP 与主 Workflow 正式接通

当前 MCP 仍是独立服务，不能算真正完成主链路集成。

### P1-5：安全和营养领域防护

- [ ] Prompt Injection 防护
- [ ] 敏感信息脱敏
- [ ] 过敏原强提醒
- [ ] 慢性病和药物相关问题识别
- [ ] 医疗免责声明
- [ ] 高风险问题拒答或转人工
- [ ] 输出事实校验
- [ ] 关键营养数据必须引用来源
- [ ] 用户记忆授权、导出和删除

### P1-6：知识库管理后台

- [ ] 文档上传
- [ ] 文档审核
- [ ] 文档版本管理
- [ ] 文档发布和下线
- [ ] 索引构建进度
- [ ] 检索测试页面
- [ ] 文档命中分析
- [ ] 知识库回滚

## 4. P2：规模化和企业运营

业务量上来之后再做。

### P2-1：多租户平台

- [ ] 租户管理
- [ ] 用户和角色管理
- [ ] 租户级模型配置
- [ ] 租户级知识库
- [ ] 租户级 Grill Profile
- [ ] 租户级费用统计
- [ ] 租户级限流

### P2-2：异步任务系统

- [ ] 文档异步解析
- [ ] 批量向量化
- [ ] 索引重建
- [ ] 大规模知识图谱构建
- [ ] 定时知识更新
- [ ] 失败任务重试

可选技术：Celery / Arq / Temporal。

### P2-3：GraphRAG 正式建设

只有在确实存在复杂关系查询时再做：

- [ ] 正式实体类型设计
- [ ] 正式关系类型设计
- [ ] 自动三元组抽取
- [ ] 图谱数据校验
- [ ] 图谱版本管理
- [ ] 图检索与向量检索融合
- [ ] 图谱评测集

当前 GraphRAG 更像演示代码，不应成为近期主线。

### P2-4：生产部署和高可用

- [ ] Docker 镜像
- [ ] Kubernetes Deployment
- [ ] 多副本
- [ ] 自动扩缩容
- [ ] 灰度发布
- [ ] 数据库主从或云数据库
- [ ] Redis 高可用
- [ ] 对象存储
- [ ] 自动备份
- [ ] 灾难恢复
- [ ] 跨区域容灾

## 5. 推荐开发顺序

```text
阶段一：统一架构
  ↓
阶段二：会话持久化与 API 安全
  ↓
阶段三：Grill v1 产品化
  ↓
阶段四：工具可靠性和可观测性
  ↓
阶段五：测试与 CI
  ↓
阶段六：RAG 质量升级
  ↓
阶段七：模型网关、MCP、流式体验
  ↓
阶段八：多租户和高可用
```

## 6. 当前基线对照（2026-10-27）

这部分只记录当前状态，不修改上面的待实现清单：

| 范围 | 当前判断 |
|---|---|
| P0-1 | 小型平台范围已完成：`ConversationRuntime`、Workflow、Tool Registry、Skill、MCP 和兼容入口已收敛到同一核心边界 |
| P0-2 | 小型平台范围已完成：统一配置、`uv.lock`、生产/开发依赖、FastAPI/Uvicorn、Docker 和 Compose 已补齐 |
| P0-3 | 小型平台范围已完成：PostgreSQL/SQLite 持久化、会话过期、归档/删除、幂等、Redis 锁和用户隔离已落地；官方 LangGraph PostgreSQL Checkpointer 与租户暂缓 |
| P0-4 | 小型平台范围已完成：FastAPI、Pydantic Schema、JWT/API Key、限流、输入约束、CORS、健康检查和统一错误码已落地；OIDC/企业 SSO 与租户权限暂缓 |
| P0-5 | 小型平台范围已完成：配置化 Profile、类型校验、依赖/冲突、置信度、拒答/换题/顺序多任务、确认门禁和统一 JSON 协议已落地；按租户加载 Profile 暂缓到 P2 |
| P0-6 | 小型平台范围已完成：统一工具 Schema、权限白名单、超时、重试退避、进程内熔断、安全错误映射、来源和结构化审计已接入；跨 Pod 熔断状态暂缓到规模化阶段 |
| P0-7 | 部分完成，已有 JSON 日志、Prometheus 和脱敏，缺少 OTel/Langfuse/告警/成本指标 |
| P0-8 | 测试与 CI 已补齐小型平台核心门禁：当前全量非浏览器测试 103 passed、1 skipped，核心路由分支覆盖率 80.50%，Ruff/Black/isort/Mypy/Helm/Playwright E2E 均通过；生产级 CD、镜像签名和平台化质量服务暂缓 |

注意：历史提交中的 `P05` 指企业级运行保障阶段；本文中的 `P0-5` 专指 Grill v1 产品化，两者不是同一阶段。

## 7. 暂时不要做的事情

- 不要同时引入多个 Agent 框架
- 不要先做复杂 GraphRAG
- 不要先上 Kubernetes
- 不要继续堆更多 MCP Server
- 不要在没有评测集前频繁更换模型
- 不要在没有会话持久化前扩展复杂记忆
- 不要在没有 Tool Policy 前开放任意工具调用

当前最重要的主线是：

```text
统一 Workflow
→ 持久化会话
→ Grill 规则稳定
→ API 安全
→ 工具可靠
→ 可观测
→ 自动化测试
→ RAG 质量
```

完成 P0 后，项目才具备继续向企业级 Agent 平台演进的基础。

### 本轮执行边界

本轮以“小型平台可交付”为完成标准，直接补齐 P0-1～P0-4 的未完成部分。以下能力明确放到 P2，不作为本轮阻塞项：

- `tenant_id` 和完整多租户权限模型；
- OIDC/企业 SSO；
- 官方 LangGraph PostgreSQL Checkpointer；
- 按租户加载 Grill Profile。

本轮交付后的实际主线是：

```text
统一 Agent 边界
→ 配置与依赖可复现
→ 会话持久化与过期治理
→ FastAPI/Pydantic API 安全
→ 小型平台 Docker/Compose 运行
→ 全量测试与浏览器验收
```
