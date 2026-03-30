"""add_auth_events_table

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, JSONB

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("ip_address", INET(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_auth_events_user_id", "auth_events", ["user_id"])
    op.create_index("idx_auth_events_occurred_at", "auth_events", ["occurred_at"])
    op.create_index("idx_auth_events_event_type", "auth_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("idx_auth_events_event_type", table_name="auth_events")
    op.drop_index("idx_auth_events_occurred_at", table_name="auth_events")
    op.drop_index("idx_auth_events_user_id", table_name="auth_events")
    op.drop_table("auth_events")
