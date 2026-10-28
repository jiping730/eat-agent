"""add small-platform tenants, memberships, and tenant-scoped data

Revision ID: 0008_multi_tenant
Revises: 0007_personal_profile
Create Date: 2026-10-28

The migration is intentionally conservative.  New tenant columns are
nullable during the upgrade so an existing local database can be upgraded
without losing data; all existing rows are then assigned to a deterministic
personal tenant.  New application writes always provide a tenant id.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op


revision = "0008_multi_tenant"
down_revision = "0007_personal_profile"
branch_labels = None
depends_on = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _personal_tenant_id(user_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"eat-agent:personal:{user_id}"))


def _add_column_if_missing(bind, table: str, column: sa.Column) -> None:
    names = {item["name"] for item in sa.inspect(bind).get_columns(table)}
    if column.name not in names:
        op.add_column(table, column)


def _json_value(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _rebuild_composite_table(bind, table_name: str) -> None:
    """Recreate old SQLite PKs so one user can own data in many tenants."""

    if bind.dialect.name != "sqlite":
        return
    legacy = f"{table_name}_legacy_0008"
    op.rename_table(table_name, legacy)
    if table_name == "memory_consents":
        op.create_table(
            table_name,
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("user_id", sa.String(128), nullable=False),
            sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "user_id"),
        )
        rows = bind.execute(sa.text(f"SELECT user_id, granted, updated_at FROM {legacy}")).mappings().all()
        for row in rows:
            bind.execute(
                sa.text(
                    f"INSERT INTO {table_name} (tenant_id, user_id, granted, updated_at) "
                    "VALUES (:tenant_id, :user_id, :granted, :updated_at)"
                ),
                {
                    "tenant_id": _personal_tenant_id(str(row["user_id"])),
                    "user_id": row["user_id"],
                    "granted": row["granted"],
                    "updated_at": row["updated_at"],
                },
            )
    else:
        op.create_table(
            table_name,
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("user_id", sa.String(128), nullable=False),
            sa.Column("height_cm", sa.Float(), nullable=True),
            sa.Column("weight_kg", sa.Float(), nullable=True),
            sa.Column("target_weight_kg", sa.Float(), nullable=True),
            sa.Column("age", sa.Integer(), nullable=True),
            sa.Column("sex", sa.String(32), nullable=True),
            sa.Column("activity_level", sa.String(32), nullable=True),
            sa.Column("health_goal", sa.String(64), nullable=True),
            sa.Column("allergies", sa.JSON(), nullable=False),
            sa.Column("dietary_preferences", sa.JSON(), nullable=False),
            sa.Column("disliked_foods", sa.JSON(), nullable=False),
            sa.Column("common_ingredients", sa.JSON(), nullable=False),
            sa.Column("meals_per_day", sa.Integer(), nullable=True),
            sa.Column("daily_budget", sa.Float(), nullable=True),
            sa.Column("consent_granted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "user_id"),
        )
        rows = bind.execute(sa.text(f"SELECT * FROM {legacy}")).mappings().all()
        for row in rows:
            values = dict(row)
            values["tenant_id"] = _personal_tenant_id(str(values["user_id"]))
            for key in ("allergies", "dietary_preferences", "disliked_foods", "common_ingredients"):
                values[key] = json.dumps(_json_value(values.get(key), []), ensure_ascii=False)
            bind.execute(
                sa.text(
                    f"INSERT INTO {table_name} (tenant_id, user_id, height_cm, weight_kg, target_weight_kg, age, sex, "
                    "activity_level, health_goal, allergies, dietary_preferences, disliked_foods, common_ingredients, "
                    "meals_per_day, daily_budget, consent_granted, version, created_at, updated_at) VALUES "
                    "(:tenant_id, :user_id, :height_cm, :weight_kg, :target_weight_kg, :age, :sex, :activity_level, "
                    ":health_goal, :allergies, :dietary_preferences, :disliked_foods, :common_ingredients, "
                    ":meals_per_day, :daily_budget, :consent_granted, :version, :created_at, :updated_at)"
                ),
                values,
            )
    op.drop_table(legacy)


def upgrade() -> None:
    bind = op.get_bind()
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)
    op.create_index("ix_tenants_owner_id", "tenants", ["owner_id"], unique=False)
    op.create_table(
        "tenant_memberships",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "user_id"),
    )
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"], unique=False)
    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("model_alias", sa.String(128), nullable=True),
        sa.Column("grill_profile", sa.JSON(), nullable=False),
        sa.Column("knowledge_scope", sa.JSON(), nullable=False),
        sa.Column("usage_limit", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )

    for table in (
        "conversations",
        "message_feedback",
        "idempotency_records",
        "user_memories",
        "user_profile_events",
        "knowledge_documents",
        "knowledge_document_versions",
        "knowledge_builds",
        "knowledge_retrieval_events",
    ):
        _add_column_if_missing(bind, table, sa.Column("tenant_id", sa.String(128), nullable=True))

    # These two tables had user_id as their sole primary key in P2-1/P1-5.
    # SQLite needs a table rebuild to make the scope part of the key.
    if bind.dialect.name == "sqlite":
        _rebuild_composite_table(bind, "memory_consents")
        _rebuild_composite_table(bind, "user_profiles")
    else:
        _add_column_if_missing(bind, "memory_consents", sa.Column("tenant_id", sa.String(128), nullable=True))
        _add_column_if_missing(bind, "user_profiles", sa.Column("tenant_id", sa.String(128), nullable=True))

    user_ids = {str(row[0]) for row in bind.execute(sa.text("SELECT id FROM users")).all()}
    for table in (
        "conversations",
        "message_feedback",
        "idempotency_records",
        "user_memories",
        "user_profile_events",
        "memory_consents",
        "user_profiles",
    ):
        try:
            user_ids.update(str(row[0]) for row in bind.execute(sa.text(f"SELECT DISTINCT user_id FROM {table}")).all())
        except sa.exc.SQLAlchemyError:
            pass
    for table, column in (
        ("knowledge_documents", "created_by"),
        ("knowledge_builds", "initiated_by"),
        ("knowledge_retrieval_events", "initiated_by"),
    ):
        user_ids.update(
            str(row[0])
            for row in bind.execute(sa.text(f"SELECT DISTINCT {column} FROM {table}")).all()
            if row[0]
        )
    for user_id in sorted(item for item in user_ids if item):
        tenant_id = _personal_tenant_id(user_id)
        now = _now()
        exists = bind.execute(sa.text("SELECT 1 FROM tenants WHERE id = :id"), {"id": tenant_id}).first()
        if exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO tenants (id, name, slug, status, owner_id, created_at, updated_at) "
                    "VALUES (:id, :name, :slug, 'active', :owner_id, :created_at, :updated_at)"
                ),
                {
                    "id": tenant_id,
                    "name": "个人空间",
                    "slug": f"personal-{tenant_id.replace('-', '')[:16]}",
                    "owner_id": user_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            bind.execute(
                sa.text(
                    "INSERT INTO tenant_memberships (tenant_id, user_id, role, status, created_at, updated_at) "
                    "VALUES (:tenant_id, :user_id, 'owner', 'active', :created_at, :updated_at)"
                ),
                {"tenant_id": tenant_id, "user_id": user_id, "created_at": now, "updated_at": now},
            )
            bind.execute(
                sa.text(
                    "INSERT INTO tenant_settings (tenant_id, grill_profile, knowledge_scope, usage_limit, created_at, updated_at) "
                    "VALUES (:tenant_id, :grill_profile, :knowledge_scope, :usage_limit, :created_at, :updated_at)"
                ),
                {
                    "tenant_id": tenant_id,
                    "grill_profile": json.dumps({}, ensure_ascii=False),
                    "knowledge_scope": json.dumps(["public"], ensure_ascii=False),
                    "usage_limit": json.dumps({}, ensure_ascii=False),
                    "created_at": now,
                    "updated_at": now,
                },
            )
        for table in (
            "conversations",
            "message_feedback",
            "idempotency_records",
            "user_memories",
            "user_profile_events",
            "memory_consents",
            "user_profiles",
        ):
            bind.execute(
                sa.text(f"UPDATE {table} SET tenant_id = :tenant_id WHERE user_id = :user_id"),
                {"tenant_id": tenant_id, "user_id": user_id},
            )
        for table, column in (
            ("knowledge_documents", "created_by"),
            ("knowledge_builds", "initiated_by"),
            ("knowledge_retrieval_events", "initiated_by"),
        ):
            bind.execute(
                sa.text(f"UPDATE {table} SET tenant_id = :tenant_id WHERE {column} = :user_id"),
                {"tenant_id": tenant_id, "user_id": user_id},
            )
        bind.execute(
            sa.text(
                "UPDATE knowledge_document_versions SET tenant_id = :tenant_id "
                "WHERE document_id IN (SELECT id FROM knowledge_documents WHERE tenant_id = :tenant_id)"
            ),
            {"tenant_id": tenant_id},
        )

    if bind.dialect.name != "sqlite":
        # PostgreSQL can change the primary-key constraint in place after the
        # deterministic backfill above.
        op.drop_constraint("memory_consents_pkey", "memory_consents", type_="primary")
        op.create_primary_key(
            "memory_consents_pkey", "memory_consents", ["tenant_id", "user_id"]
        )
        op.drop_constraint("user_profiles_pkey", "user_profiles", type_="primary")
        op.create_primary_key("user_profiles_pkey", "user_profiles", ["tenant_id", "user_id"])

    for table in (
        "conversations",
        "message_feedback",
        "idempotency_records",
        "user_memories",
        "user_profile_events",
        "knowledge_documents",
        "knowledge_document_versions",
        "knowledge_builds",
        "knowledge_retrieval_events",
    ):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "knowledge_retrieval_events",
        "knowledge_builds",
        "knowledge_documents",
        "user_profile_events",
        "user_memories",
        "idempotency_records",
        "message_feedback",
        "conversations",
    ):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
    if bind.dialect.name == "sqlite":
        # A downgrade is deliberately conservative; tenant data is not deleted.
        pass
    op.drop_table("tenant_settings")
    op.drop_index("ix_tenant_memberships_user_id", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")
    op.drop_index("ix_tenants_owner_id", table_name="tenants")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")

