# 数据库运维脚本

这些脚本不在应用启动路径中执行，用于人工或定时任务完成 PostgreSQL 备份和恢复演练。

## 备份

```bash
DATABASE_URL='postgresql+psycopg://user:password@host:5432/eat_agent' \
  python scripts/backup_postgres.py --output backups/eat-agent-20261027.dump
```

脚本使用 `pg_dump --format=custom`，不会把连接密码打印到日志。

## 恢复

恢复会覆盖目标数据库对象，必须显式传入 `--confirm`：

```bash
DATABASE_URL='postgresql+psycopg://user:password@host:5432/eat_agent_restore' \
  python scripts/restore_postgres.py backups/eat-agent-20261027.dump --confirm
```

建议先恢复到临时数据库，验证用户、会话、消息和 `GrillContext` 后再执行生产恢复。

## 本地平台运维

P2-4 当前先交付可重复的本地启动和运行检查；备份/恢复功能暂缓，现有 PostgreSQL
脚本保持不变。

```powershell
./scripts/platform.ps1 start    # 构建并启动，等待 eat-agent 健康
./scripts/platform.ps1 status
./scripts/platform.ps1 logs
./scripts/platform.ps1 restart
./scripts/platform.ps1 stop     # 不删除数据卷
```

启动流程会先执行只读迁移预检，再执行 `alembic upgrade head`。查看迁移状态：

```bash
python scripts/migration_check.py
python scripts/migration_check.py --require-up-to-date
```

普通检查允许报告待执行迁移；`--require-up-to-date` 用于升级后的 CI/发布门禁。

Docker 清理默认为 dry-run，只保留运行中镜像和最近两个 `eat-agent` 镜像版本：

```bash
python scripts/docker_cleanup.py
python scripts/docker_cleanup.py --confirm
```

清理不会删除卷，也不会使用 `docker system prune -a`。BuildKit 缓存没有可靠的
Compose 项目归属信息，因此确认清理时只处理七天以前的缓存；如暂不清理缓存，追加
`--no-builder-cache`。
