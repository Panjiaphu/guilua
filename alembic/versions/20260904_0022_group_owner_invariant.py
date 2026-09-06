"""enforce one active owner per Group space

Revision ID: 20260904_0022
Revises: 20260904_0021
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260904_0022"
down_revision = "20260904_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_group_memberships_active_owner",
        "group_memberships",
        ["space_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active' AND role = 'owner'"),
        postgresql_where=sa.text("status = 'active' AND role = 'owner'"),
    )


def downgrade() -> None:
    op.drop_index("uq_group_memberships_active_owner", table_name="group_memberships")
