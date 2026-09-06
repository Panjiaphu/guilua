"""separate Group media invitation and provider connection state

Revision ID: 20260904_0020
Revises: 20260903_0019
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260904_0020"
down_revision = "20260903_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "group_media_participants",
        sa.Column(
            "connection_status",
            sa.String(20),
            nullable=False,
            server_default="not_connected",
        ),
    )
    op.add_column(
        "group_media_participants",
        sa.Column(
            "connection_error_code",
            sa.String(80),
            nullable=False,
            server_default="",
        ),
    )
    op.create_check_constraint(
        "ck_group_media_participants_connection",
        "group_media_participants",
        "connection_status IN ('not_connected','connecting','connected','reconnecting','failed')",
    )
    op.create_index(
        "ix_group_media_participants_session_connection",
        "group_media_participants",
        ["session_id", "connection_status"],
    )
    op.execute(
        sa.text(
            """
            UPDATE group_media_participants AS participant
            SET connection_status = 'connected'
            FROM group_media_sessions AS session
            WHERE participant.session_id = session.id
              AND participant.invite_status = 'joined'
              AND session.status = 'active'
            """
        )
    )
    op.alter_column(
        "group_media_participants",
        "connection_status",
        server_default=None,
    )
    op.alter_column(
        "group_media_participants",
        "connection_error_code",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_group_media_participants_session_connection",
        table_name="group_media_participants",
    )
    op.drop_constraint(
        "ck_group_media_participants_connection",
        "group_media_participants",
        type_="check",
    )
    op.drop_column("group_media_participants", "connection_error_code")
    op.drop_column("group_media_participants", "connection_status")
