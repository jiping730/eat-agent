"""Add personal knowledge scope and owner isolation.

Revision ID: 0010_p2_3_personal_knowledge
Revises: 0009_p2_2_conversation_experience
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_p2_3_personal_knowledge"
down_revision = "0009_p2_2_conversation_experience"
branch_labels = None
depends_on = None


def _add_column_if_missing(bind, table: str, column: sa.Column) -> None:
    names = {item["name"] for item in sa.inspect(bind).get_columns(table)}
    if column.name not in names:
        op.add_column(table, column)


def _rebuild_documents_for_sqlite(bind) -> None:
    """Replace the old tenant/source unique key without losing versions."""

    legacy = "knowledge_documents_legacy_0010"
    op.rename_table("knowledge_documents", legacy)
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=True),
        sa.Column("scope", sa.String(32), nullable=False, server_default="tenant"),
        sa.Column("owner_user_id", sa.String(128), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_name", sa.String(256), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("latest_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("access_groups", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("reviewed_by", sa.String(128), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "scope",
            "owner_user_id",
            "source_name",
            name="uq_knowledge_scope_owner_source_name",
        ),
    )
    rows = bind.execute(sa.text(f"SELECT * FROM {legacy}")).mappings().all()
    for row in rows:
        values = dict(row)
        values.setdefault("scope", "tenant")
        values.setdefault("owner_user_id", None)
        values.setdefault("deleted_at", None)
        bind.execute(
            sa.text(
                "INSERT INTO knowledge_documents (id, tenant_id, scope, owner_user_id, deleted_at, source_name, title, "
                "status, latest_version, published_version, access_groups, created_by, updated_by, reviewed_by, "
                "review_note, created_at, updated_at) VALUES (:id, :tenant_id, :scope, :owner_user_id, :deleted_at, "
                ":source_name, :title, :status, :latest_version, :published_version, :access_groups, :created_by, "
                ":updated_by, :reviewed_by, :review_note, :created_at, :updated_at)"
            ),
            values,
        )
    op.drop_table(legacy)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _rebuild_documents_for_sqlite(bind)
    else:
        _add_column_if_missing(
            bind,
            "knowledge_documents",
            sa.Column("scope", sa.String(32), nullable=False, server_default="tenant"),
        )
        _add_column_if_missing(bind, "knowledge_documents", sa.Column("owner_user_id", sa.String(128), nullable=True))
        _add_column_if_missing(
            bind,
            "knowledge_documents",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.drop_constraint("uq_knowledge_tenant_source_name", "knowledge_documents", type_="unique")
        op.create_unique_constraint(
            "uq_knowledge_scope_owner_source_name",
            "knowledge_documents",
            ["tenant_id", "scope", "owner_user_id", "source_name"],
        )

    _add_column_if_missing(
        bind,
        "knowledge_builds",
        sa.Column("scope", sa.String(32), nullable=False, server_default="tenant"),
    )
    _add_column_if_missing(bind, "knowledge_builds", sa.Column("owner_user_id", sa.String(128), nullable=True))
    _add_column_if_missing(
        bind,
        "knowledge_retrieval_events",
        sa.Column("scope", sa.String(32), nullable=False, server_default="tenant"),
    )
    _add_column_if_missing(
        bind,
        "knowledge_retrieval_events",
        sa.Column("owner_user_id", sa.String(128), nullable=True),
    )

    op.create_index("ix_knowledge_documents_scope", "knowledge_documents", ["scope"], unique=False)
    op.create_index("ix_knowledge_documents_owner_user_id", "knowledge_documents", ["owner_user_id"], unique=False)
    op.create_index("ix_knowledge_builds_scope", "knowledge_builds", ["scope"], unique=False)
    op.create_index("ix_knowledge_builds_owner_user_id", "knowledge_builds", ["owner_user_id"], unique=False)
    op.create_index("ix_knowledge_retrieval_events_scope", "knowledge_retrieval_events", ["scope"], unique=False)
    op.create_index(
        "ix_knowledge_retrieval_events_owner_user_id",
        "knowledge_retrieval_events",
        ["owner_user_id"],
        unique=False,
    )


def downgrade() -> None:
    # The migration is additive for PostgreSQL. SQLite column removal would
    # require another full table rebuild; keep the data rather than risk a
    # destructive downgrade in a local personal database.
    for index_name, table_name in (
        ("ix_knowledge_retrieval_events_owner_user_id", "knowledge_retrieval_events"),
        ("ix_knowledge_retrieval_events_scope", "knowledge_retrieval_events"),
        ("ix_knowledge_builds_owner_user_id", "knowledge_builds"),
        ("ix_knowledge_builds_scope", "knowledge_builds"),
        ("ix_knowledge_documents_owner_user_id", "knowledge_documents"),
        ("ix_knowledge_documents_scope", "knowledge_documents"),
    ):
        op.drop_index(index_name, table_name=table_name)
