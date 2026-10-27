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
