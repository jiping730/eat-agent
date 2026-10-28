"""add platform users, conversation metadata, and idempotency

Revision ID: 0002_platform_auth_idempotency
Revises: 0001_create_conversations
Create Date: 2026-10-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_platform_auth_idempotency"
down_revision = "0001_create_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], unique=False)
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    op.add_column("conversations", sa.Column("title", sa.String(length=200), nullable=False, server_default="新会话"))
    op.add_column("conversations", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("conversations", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_idempotency_conversation_request"),
    )
    op.create_index("ix_idempotency_records_conversation_id", "idempotency_records", ["conversation_id"], unique=False)
    op.create_index("ix_idempotency_records_user_id", "idempotency_records", ["user_id"], unique=False)

    with op.batch_alter_table("messages") as batch_op:
        batch_op.create_unique_constraint("uq_messages_request_role", ["conversation_id", "request_id", "role"])


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint("uq_messages_request_role", type_="unique")
    op.drop_index("ix_idempotency_records_user_id", table_name="idempotency_records")
    op.drop_index("ix_idempotency_records_conversation_id", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_column("conversations", "archived_at")
    op.drop_column("conversations", "version")
    op.drop_column("conversations", "title")
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
