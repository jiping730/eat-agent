# P05 实施文档：企业级运行保障与交付验收

> 状态：已完成，可交付
>
> 实施日期：2026-10-27
>
> 版本：`0.5.0`

## 1. 阶段目标

P05 面向个人企业项目的小型平台目标，补齐 P04 之后影响长期运行和交付可信度的能力：

- Prometheus 指标和结构化日志；
- CI 自动检查；
- PostgreSQL 备份与恢复工具；
- 生产安全配置校验和容器运行时加固；
- Helm 生产安全默认值；
- Grill 质量回归样例；
- 最终镜像、Compose、健康检查和资源清理验收。

本阶段继续采用模块化单体，不拆分微服务，不引入 Kafka、Service Mesh、Keycloak 或 Operator。Compose 继续用于本地开发，Kubernetes + Helm 继续作为部署层。

## 2. 实际代码改动

### 2.1 可观测性

新增 `core/observability.py`，统一定义 Prometheus 指标：

- `eat_agent_http_requests_total`：按方法、稳定路径和状态码统计 HTTP 请求；
- `eat_agent_http_request_duration_seconds`：HTTP 延迟；
- `eat_agent_conversation_responses_total`：回答、追问、降级等会话结果；
- `eat_agent_conversation_duration_seconds`：会话处理耗时；
- `eat_agent_grill_decisions_total`：Grill 决策动作和目标字段；
- `eat_agent_llm_requests_total`、`eat_agent_llm_duration_seconds`：模型调用成功、失败和 fallback；
- `eat_agent_rate_limit_rejections_total`：限流拒绝；
- `eat_agent_info`：版本和运行环境。

修改 `front/app.py`：

- 增加 `/metrics`；
- 生产模式可以通过 `METRICS_API_KEY` 和 `X-Metrics-Token` / Bearer Token 保护指标；
- 路径标签会把 `/conversations/<id>` 归一化为 `/conversations/:id`，避免会话 ID 造成高基数；
- 每个请求保留 `X-Request-ID`；
- 记录注册、登录、刷新成功等审计事件，但不记录密码、Token 或原始问题。

### 2.2 日志脱敏

修改 `core/logging_config.py`、`core/workflow.py` 和 `utils/llm.py`：

- 对 Token、密码、Secret、API Key、Authorization 等字段进行脱敏；
- 用户标识只记录不可逆短指纹；
- Workflow 日志不再输出用户原始问题、工具返回内容或 Grill 上下文；
- LLM 错误只输出类型和稳定错误标签，不把外部异常原文直接写入日志。

### 2.3 生产安全配置

修改 `config.py` 和 `.env.example`：

- 增加 `STRICT_SECURITY`、`METRICS_ENABLED`、`METRICS_API_KEY`；
- `APP_ENV=production` 且启用严格模式时，启动前检查：JWT 模式、JWT Secret 长度、PostgreSQL、Redis、CORS 和 metrics 密钥；
- 默认应用版本提升为 `0.5.0`；
- 错误配置在启动阶段直接失败，避免服务以不安全配置运行。

### 2.4 容器安全

修改 `Dockerfile`：

- 创建固定 UID/GID `10001` 的 `appuser/appgroup`；
- 应用进程不再以 root 运行；
- `/app`、`/app/data` 和 `/tmp` 的权限在镜像构建时准备好。

修改 `docker-compose.yml`：

- 应用镜像标签更新为 `eat-agent:p05`；
- 默认使用开发环境配置，生产环境通过环境变量覆盖；
- 保留 PostgreSQL、Redis 健康依赖和应用健康检查。

### 2.5 Helm 生产加固

修改 `deploy/helm/eat-agent`：

- Chart 和默认镜像版本提升到 `0.5.0`；
- Deployment 设置 `runAsNonRoot`、固定用户、只读根文件系统、丢弃 Linux capabilities 和 RuntimeDefault seccomp；
- `/app/data` 和 `/tmp` 使用临时卷；
- 生产默认开启严格安全配置；
- 外部 Secret 强制提供 `DATABASE_URL`、`JWT_SECRET` 和 `METRICS_API_KEY`；
- 增加可选 ServiceMonitor，默认关闭，避免没有 Prometheus Operator 时部署失败。

### 2.6 备份恢复工具

新增：

- `scripts/backup_postgres.py`：生成 PostgreSQL custom-format、无 owner 的备份；
- `scripts/restore_postgres.py`：要求显式传入 `--confirm`，并使用 `--clean --if-exists` 恢复；
- `scripts/README.md`：说明日常备份、恢复演练和生产注意事项。

脚本兼容项目默认的 `postgresql+psycopg://` SQLAlchemy URL，会在调用 `pg_dump/pg_restore` 前归一化为 libpq 兼容的 `postgresql://` URL。备份文件目录已加入 `.gitignore` 和 `.dockerignore`，不会进入 Git 或构建上下文。

### 2.7 Grill 质量回归与 CI

新增 `evaluation/grill_cases.json`，覆盖：

- 餐食规划首轮缺少餐次时追问；
- 补充餐次后继续追问过敏/忌口；
- 补齐关键信息后执行；
- 热量查询缺少食物时追问。

新增 `test_p05_operations.py`，覆盖：

- 生产安全配置拒绝不安全默认值；
- 日志敏感信息脱敏；
- Prometheus 指标稳定名称和低基数路径；
- Grill 评测样例；
- PostgreSQL URL 归一化。

新增 `.github/workflows/ci.yml`，执行依赖安装、编译检查、pytest 和 Helm lint/render。

## 3. 实际验收记录

### 3.1 代码与静态检查

已通过：

```text
git diff --check
python -m compileall -q core front utils scripts evaluation
helm lint deploy/helm/eat-agent
helm template eat-agent deploy/helm/eat-agent
```

Helm 结果：

```text
1 chart(s) linted, 0 chart(s) failed
```

### 3.2 最终镜像和 Compose

最终镜像：

```text
eat-agent:p05
image digest: sha256:1cf5fad5c4d9121fe5e5b90d3d0972d6dc82e283d626d7d68559133aa39c09dc
```

实际运行的应用容器：

```text
eat-agent-p03-test-eat-agent-1
```

验收结果：

- 容器用户为 `appuser`，UID/GID 为 `10001`；
- `GET /healthz` 返回 HTTP 200，版本为 `0.5.0`；
- `GET /readyz` 返回 HTTP 200；
- 开发环境 `GET /metrics` 返回 Prometheus 文本格式；
- 指标路径使用稳定标签，不包含 `conversation_id`；
- PostgreSQL、Redis 和应用容器均为 healthy/running。

### 3.3 最终镜像全量测试

在最终 `eat-agent:p05` 镜像中临时安装 pytest 并运行全部测试，pytest 依赖只存在于一次性容器，未写入生产镜像：

```text
...........................                                              [100%]
27 passed in 2.88s
```

覆盖 P0/P01/P02/P03/P04 和 P05 的架构、追问、持久化、认证、幂等、运行安全、指标和 Grill 回归。

### 3.4 浏览器多轮对话

在 `http://127.0.0.1:5000/` 的真实浏览器页面完成：

```text
用户：我想减肥
  → Agent：你想安排哪一餐？
  → 点击：早餐
  → Agent：你有需要避开的食物或过敏原吗？
  → 点击：没有过敏或忌口
  → Agent：给出餐食规划
  → 页面状态：已完成回答
```

页面实际显示了候选按钮、两次追问和最终回答，响应时间与检索次数也正常显示。由于环境没有配置真实模型 Key，最终回答使用项目已有的可解释离线降级路径。

### 3.5 PostgreSQL 备份恢复

使用当前本地 P03 测试 PostgreSQL 容器完成 custom-format 备份、目录检查和恢复演练：

```text
TOC Entries: 49
Format: CUSTOM
backup_restore_ok
```

此外验证了脚本对项目默认 `postgresql+psycopg://` URL 的归一化，以及恢复脚本没有 `--confirm` 时会拒绝执行。

### 3.6 Kubernetes 边界

本机当前 `kubectl cluster-info` 仍无法连接 Kubernetes API（默认 `localhost:8080` 无服务）。因此本阶段已完成并确认：

- Helm lint 通过；
- Helm template 渲染通过；
- 安全上下文、探针、Secret、ServiceMonitor 等资源静态结构可渲染。

本机未完成真实集群 apply、Pod 滚动升级、Ingress、HPA 和 ServiceMonitor 运行态验收，不能把它们宣称为已通过。

## 4. 资源清理和交付状态

- 最新可运行镜像保留为 `eat-agent:p05`；
- 失败构建产生的临时容器和 pytest 容器均使用 `--rm`，不保留；
- 备份文件目录和备份构建上下文已排除；
- P04 旧镜像已删除，Docker Builder 可回收缓存已清空（清理前约 1.727GB）；
- 生产数据库数据卷未删除；
- 真实模型 Key 未写入代码、镜像或 Git。

## 5. P05 后仍需结合生产环境完成的事项

- 启用 Docker Desktop Kubernetes 或连接实际集群，完成真实部署验收；
- 接入 Prometheus/Grafana/Alertmanager，并为关键指标配置告警；
- 按实际域名配置 TLS、Ingress、证书续期和安全响应头；
- 将 Redis/PostgreSQL 替换为生产级高可用或托管服务；
- 将备份脚本接入定时任务、对象存储、保留策略和定期恢复演练；
- 增加完整 RBAC、企业 SSO/OIDC、审计留存和数据访问审批；
- 配置真实模型 Key 后，补充模型质量、成本、延迟和安全评测。
