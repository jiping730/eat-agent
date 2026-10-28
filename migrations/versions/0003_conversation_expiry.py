"""add conversation expiry timestamps

Revision ID: 0003_conversation_expiry
Revises: 0002_platform_auth_idempotency
Create Date: 2026-10-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_conversation_expiry"
down_revision = "0002_platform_auth_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "UPDATE conversations SET expires_at = datetime('now', '+30 days') WHERE expires_at IS NULL"
        )
    else:
        op.execute(
            "UPDATE conversations "
            "SET expires_at = CURRENT_TIMESTAMP + INTERVAL '30 days' "
            "WHERE expires_at IS NULL"
        )
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.alter_column("expires_at", nullable=False)
    op.create_index("ix_conversations_expires_at", "conversations", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_conversations_expires_at", table_name="conversations")
    op.drop_column("conversations", "expires_at")
