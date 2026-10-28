"""add message feedback for the streaming conversation experience

Revision ID: 0004_streaming_feedback
Revises: 0003_conversation_expiry
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_streaming_feedback"
down_revision = "0003_conversation_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("rating", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_message_feedback_user"),
    )
    op.create_index("ix_message_feedback_message_id", "message_feedback", ["message_id"], unique=False)
    op.create_index("ix_message_feedback_conversation_id", "message_feedback", ["conversation_id"], unique=False)
    op.create_index("ix_message_feedback_user_id", "message_feedback", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_message_feedback_user_id", table_name="message_feedback")
    op.drop_index("ix_message_feedback_conversation_id", table_name="message_feedback")
    op.drop_index("ix_message_feedback_message_id", table_name="message_feedback")
    op.drop_table("message_feedback")
