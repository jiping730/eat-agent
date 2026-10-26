"""create durable conversations and messages

Revision ID: 0001_create_conversations
Revises:
Create Date: 2026-10-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_create_conversations"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("current_goal", sa.String(length=64), nullable=True),
        sa.Column("grill_context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("response_type", sa.String(length=32), nullable=True),
        sa.Column("target_field", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"], unique=False)
    op.create_index("ix_messages_request_id", "messages", ["request_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_messages_request_id", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
