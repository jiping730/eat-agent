# P2-4：本地部署与运行维护实施说明

## 1. 范围

本阶段面向个人使用和少量用户的小型平台，目标是让本地 Docker Compose 运行、升级检查、健康确认和空间清理可重复执行。

用户已明确暂缓以下内容：

- SQLite/PostgreSQL 备份与恢复；
- 个人档案、会话和知识库导出/导入；
- 备份保留策略、对象存储和恢复演练。

已有 `scripts/backup_postgres.py`、`scripts/restore_postgres.py` 保留，不在本阶段扩展。

## 2. 实际实现

### 2.1 Compose 运维入口

`scripts/platform.ps1` 提供五个动作：

| 动作 | 行为 |
|---|---|
| `start` | `docker compose up -d --build`，等待应用健康检查 |
| `stop` | 停止服务，不删除容器卷 |
| `restart` | 重启现有服务并等待健康检查 |
| `status` | 查看 PostgreSQL、Redis 和 eat-agent 状态 |
| `logs` | 查看最近 200 行并持续跟踪日志 |

Compose 的应用镜像默认是 `eat-agent:p2-4`，也可以通过 `APP_IMAGE` 覆盖。应用容器启动时先运行迁移预检，再运行 `alembic upgrade head`，最后启动 Gunicorn。

### 2.2 Alembic 迁移预检

`scripts/migration_check.py` 使用 Alembic 原生 API 读取：

- 数据库是否可连接；
- 当前数据库 revision；
- 代码仓库的 migration Head；
- 是否存在多个 Head；
- 当前是否有待执行迁移。

普通命令用于启动前报告状态；`--require-up-to-date` 用于 CI 或升级后的严格门禁。脚本只输出数据库后端和 revision，不输出连接串密码。

### 2.3 JSON 日志轮转

控制台 JSON 日志继续作为默认方式，适合 Docker Desktop 查看。配置以下变量后，可以额外写入本地 JSONL 文件：

```text
LOG_FILE=logs/eat-agent.jsonl
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5
```

文件使用 `RotatingFileHandler` 按大小轮转，保留敏感信息脱敏和现有 trace/request 字段。日志配置是幂等的，模块重复初始化不会重复添加相同文件处理器。

### 2.4 健康检查

- `/health/live` 只确认应用进程仍能响应。
- `/health/ready` 和 `/readyz` 检查数据库连接；如果启用了 Redis，还检查协调器连接。
- 返回 `checks.database` 和 `checks.coordination`，依赖故障时返回 503。
- 未启用 Redis 时状态为 `disabled`，不把可选依赖误判成故障。

### 2.5 Docker 清理

`scripts/docker_cleanup.py` 默认只生成清理计划。必须追加 `--confirm` 才会执行：

```bash
python scripts/docker_cleanup.py
python scripts/docker_cleanup.py --confirm
```

计划会：

- 清理当前 Compose 项目已停止的容器；
- 保留运行中容器正在使用的镜像；
- 默认保留最近两个 `eat-agent` 镜像，给当前版本留一个回滚点；
- 清理旧项目镜像时不使用强制删除；
- 确认后最多清理七天以前的 BuildKit 缓存；
- 永不删除 PostgreSQL、Redis 或应用数据卷。

Docker BuildKit 缓存没有可靠的 Compose 项目归属标签，因此脚本对缓存采用时间阈值而不是宣称精确项目隔离；如果希望暂不处理缓存，使用 `--no-builder-cache`。

## 3. 验收口径

本阶段专项测试覆盖迁移状态检查、JSON 日志轮转、健康检查、Docker 清理计划和 Compose 脚本参数保护。完整测试结果以 `docs/implementation-record.md` 的 P2-4 实际验收记录为准。
