"""add explicit personal profile and profile audit events

Revision ID: 0007_personal_profile
Revises: 0006_knowledge_base_management
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op


revision = "0007_personal_profile"
down_revision = "0006_knowledge_base_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("target_weight_kg", sa.Float(), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("sex", sa.String(length=32), nullable=True),
        sa.Column("activity_level", sa.String(length=32), nullable=True),
        sa.Column("health_goal", sa.String(length=64), nullable=True),
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
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "user_profile_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_profile_events_user_id", "user_profile_events", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_profile_events_user_id", table_name="user_profile_events")
    op.drop_table("user_profile_events")
    op.drop_table("user_profiles")
