"""Restore a PostgreSQL custom-format backup with an explicit destructive guard."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def _pg_database_url(database_url: str) -> str:
    """Convert SQLAlchemy's psycopg URL to a libpq-compatible URL."""
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a PostgreSQL custom-format backup")
    parser.add_argument("backup", type=Path)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required because restore replaces objects in the target database",
    )
    args = parser.parse_args()

    if not args.confirm:
        raise SystemExit("恢复会覆盖目标数据库，请显式传入 --confirm")
    if not args.backup.is_file():
        raise SystemExit(f"备份文件不存在: {args.backup}")

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+")):
        raise SystemExit("DATABASE_URL 必须是 PostgreSQL URL")

    command = [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--dbname",
        _pg_database_url(database_url),
        str(args.backup),
    ]
    subprocess.run(command, check=True)
    print(f"PostgreSQL backup restored: {args.backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
