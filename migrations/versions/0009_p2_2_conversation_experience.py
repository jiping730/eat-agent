"""P2-2 conversation experience state.

Revision ID: 0009_p2_2_conversation_experience
Revises: 0008_multi_tenant
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_p2_2_conversation_experience"
down_revision = "0008_multi_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profile_suggestions",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_profile_suggestions_tenant_id", "profile_suggestions", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_profile_suggestions_user_id", "profile_suggestions", ["user_id"], unique=False
    )
    op.create_index(
        "ix_profile_suggestions_conversation_id", "profile_suggestions", ["conversation_id"], unique=False
    )
    op.create_index(
        "ix_profile_suggestions_status", "profile_suggestions", ["status"], unique=False
    )

    op.create_table(
        "user_experience_settings",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("show_model_info", sa.Boolean(), nullable=False),
        sa.Column("show_sources", sa.Boolean(), nullable=False),
        sa.Column("show_safety_details", sa.Boolean(), nullable=False),
        sa.Column("answer_style", sa.String(length=32), nullable=False),
        sa.Column("pinned_shortcuts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_experience_settings")
    op.drop_index("ix_profile_suggestions_status", table_name="profile_suggestions")
    op.drop_index("ix_profile_suggestions_conversation_id", table_name="profile_suggestions")
    op.drop_index("ix_profile_suggestions_user_id", table_name="profile_suggestions")
    op.drop_index("ix_profile_suggestions_tenant_id", table_name="profile_suggestions")
    op.drop_table("profile_suggestions")
