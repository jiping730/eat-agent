"""add explicit memory consent and user-owned memory records

Revision ID: 0005_memory_governance
Revises: 0004_streaming_feedback
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_memory_governance"
down_revision = "0004_streaming_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_consents",
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "user_memories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("user_input", sa.Text(), nullable=False),
        sa.Column("assistant_output", sa.Text(), nullable=False),
        sa.Column("quality", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_memories_user_id", "user_memories", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_memories_user_id", table_name="user_memories")
    op.drop_table("user_memories")
    op.drop_table("memory_consents")
