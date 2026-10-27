"""Create a PostgreSQL custom-format backup without logging credentials."""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def _safe_database_name(database_url: str) -> str:
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    return (parsed.path.strip("/") or "eat_agent").replace("/", "_")


def _pg_database_url(database_url: str) -> str:
    """Convert SQLAlchemy's psycopg URL to a libpq-compatible URL."""
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a PostgreSQL custom-format backup")
    parser.add_argument("--output", type=Path, help="Backup file path")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+")):
        raise SystemExit("DATABASE_URL 必须是 PostgreSQL URL")

    output = args.output or Path("backups") / (
        f"{_safe_database_name(database_url)}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.dump"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--file",
        str(output),
        _pg_database_url(database_url),
    ]
    subprocess.run(command, check=True)
    print(f"PostgreSQL backup created: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
