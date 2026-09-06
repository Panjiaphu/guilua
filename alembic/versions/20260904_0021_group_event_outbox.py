"""durable Group invalidation outbox for cross-instance fan-out

Revision ID: 20260904_0021
Revises: 20260904_0020
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260904_0021"
down_revision = "20260904_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_event_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("space_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending','published','failed')", name="ck_group_event_outbox_status"),
        sa.ForeignKeyConstraint(["space_id"], ["group_spaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_group_event_outbox_delivery",
        "group_event_outbox",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_group_event_outbox_space_created",
        "group_event_outbox",
        ["space_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_group_event_outbox_space_created", table_name="group_event_outbox")
    op.drop_index("ix_group_event_outbox_delivery", table_name="group_event_outbox")
    op.drop_table("group_event_outbox")
