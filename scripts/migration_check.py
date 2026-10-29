"""Check database connectivity and Alembic drift before or after an upgrade.

The normal command is a read-only preflight and exits successfully when the
database is reachable, even when migrations are pending.  CI or deployment
can add ``--require-up-to-date`` to turn pending migrations into a failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import settings  # noqa: E402


@dataclass(frozen=True)
class MigrationStatus:
    database: str
    current_heads: tuple[str, ...]
    heads: tuple[str, ...]
    pending: bool
    multiple_heads: bool

    @property
    def up_to_date(self) -> bool:
        return not self.pending and not self.multiple_heads

    def to_dict(self) -> dict[str, Any]:
        return {
            "database": self.database,
            "current_heads": list(self.current_heads),
            "heads": list(self.heads),
            "pending": self.pending,
            "multiple_heads": self.multiple_heads,
            "up_to_date": self.up_to_date,
        }


def _alembic_config() -> Config:
    config = Config(str(ROOT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT_DIR / "migrations"))
    return config


def _database_engine():
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)


def inspect_migrations() -> MigrationStatus:
    """Read the current database revision and repository heads."""

    script = ScriptDirectory.from_config(_alembic_config())
    heads = tuple(sorted(script.get_heads()))
    engine = _database_engine()
    try:
        with engine.connect() as connection:
            migration_context = MigrationContext.configure(connection)
            current_heads = tuple(sorted(migration_context.get_current_heads()))
            # A fresh database has no current revision and therefore needs all
            # migrations.  This is a reportable state, not a connectivity error.
    finally:
        engine.dispose()

    database_name = engine.url.get_backend_name()
    return MigrationStatus(
        database=database_name,
        current_heads=current_heads,
        heads=heads,
        pending=set(current_heads) != set(heads),
        multiple_heads=len(heads) > 1,
    )


def _print_status(status: MigrationStatus, as_json: bool) -> None:
    payload = status.to_dict()
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(f"database: {status.database}")
    print(f"current heads: {', '.join(status.current_heads) if status.current_heads else '(base)'}")
    print(f"repository heads: {', '.join(status.heads) if status.heads else '(none)'}")
    print(f"pending migrations: {'yes' if status.pending else 'no'}")
    print(f"multiple heads: {'yes' if status.multiple_heads else 'no'}")
    print(f"status: {'up-to-date' if status.up_to_date else 'needs-attention'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Alembic migration status")
    parser.add_argument(
        "--require-up-to-date",
        action="store_true",
        help="fail when migrations are pending or the repository has multiple heads",
    )
    parser.add_argument("--json", action="store_true", help="print a machine-readable JSON result")
    args = parser.parse_args(argv)

    try:
        status = inspect_migrations()
    except Exception as exc:  # pragma: no cover - exercised through CLI integration
        # Do not echo SQLAlchemy's raw exception: driver messages can contain
        # connection details and deployment-specific host information.
        payload = {
            "status": "error",
            "error_type": type(exc).__name__,
            "message": "database connection or migration metadata check failed",
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"migration check failed: {type(exc).__name__}", file=sys.stderr)
        return 2

    _print_status(status, args.json)
    if status.multiple_heads or (args.require_up_to_date and not status.up_to_date):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
