"""service requests

Revision ID: 20260619_0003
Revises: 20260618_0002
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260619_0003"
down_revision = "20260618_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference_code", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("service_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("target_region", sa.String(length=64), nullable=False),
        sa.Column("protocol", sa.String(length=64), nullable=False),
        sa.Column("duration_hours", sa.Integer(), nullable=False),
        sa.Column("device_label", sa.String(length=120), nullable=False),
        sa.Column("current_ip", sa.String(length=80), nullable=False),
        sa.Column("member_note", sa.Text(), nullable=False),
        sa.Column("assigned_endpoint", sa.String(length=255), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference_code"),
    )
    op.create_index(op.f("ix_service_requests_reference_code"), "service_requests", ["reference_code"], unique=False)
    op.create_index(op.f("ix_service_requests_service_type"), "service_requests", ["service_type"], unique=False)
    op.create_index(op.f("ix_service_requests_status"), "service_requests", ["status"], unique=False)
    op.create_index(op.f("ix_service_requests_user_id"), "service_requests", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_service_requests_user_id"), table_name="service_requests")
    op.drop_index(op.f("ix_service_requests_status"), table_name="service_requests")
    op.drop_index(op.f("ix_service_requests_service_type"), table_name="service_requests")
    op.drop_index(op.f("ix_service_requests_reference_code"), table_name="service_requests")
    op.drop_table("service_requests")
