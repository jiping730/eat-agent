"""add managed knowledge-base lifecycle and build analytics

Revision ID: 0006_knowledge_base_management
Revises: 0005_memory_governance
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_knowledge_base_management"
down_revision = "0005_memory_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("source_name", sa.String(length=256), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("access_groups", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_name"),
    )
    op.create_index("ix_knowledge_documents_source_name", "knowledge_documents", ["source_name"], unique=True)
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"], unique=False)

    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version"),
    )
    op.create_index(
        "ix_knowledge_document_versions_document_id",
        "knowledge_document_versions",
        ["document_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_builds",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("index_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("initiated_by", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("index_version"),
    )
    op.create_index("ix_knowledge_builds_index_version", "knowledge_builds", ["index_version"], unique=True)
    op.create_index("ix_knowledge_builds_status", "knowledge_builds", ["status"], unique=False)

    op.create_table(
        "knowledge_retrieval_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("query", sa.String(length=2000), nullable=False),
        sa.Column("access_groups", sa.JSON(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("result_document_ids", sa.JSON(), nullable=False),
        sa.Column("initiated_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_retrieval_events_created_at",
        "knowledge_retrieval_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_retrieval_events_created_at", table_name="knowledge_retrieval_events")
    op.drop_table("knowledge_retrieval_events")
    op.drop_index("ix_knowledge_builds_status", table_name="knowledge_builds")
    op.drop_index("ix_knowledge_builds_index_version", table_name="knowledge_builds")
    op.drop_table("knowledge_builds")
    op.drop_index("ix_knowledge_document_versions_document_id", table_name="knowledge_document_versions")
    op.drop_table("knowledge_document_versions")
    op.drop_index("ix_knowledge_documents_status", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_source_name", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
