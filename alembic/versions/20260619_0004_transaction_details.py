"""transaction details

Revision ID: 20260619_0004
Revises: 20260619_0003
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa


revision = "20260619_0004"
down_revision = "20260619_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transaction_requests", sa.Column("contact_phone", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("transaction_requests", sa.Column("contact_line", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("transaction_requests", sa.Column("usdt_network", sa.String(length=32), nullable=False, server_default=""))
    op.add_column("transaction_requests", sa.Column("wallet_address", sa.String(length=255), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("transaction_requests", "wallet_address")
    op.drop_column("transaction_requests", "usdt_network")
    op.drop_column("transaction_requests", "contact_line")
    op.drop_column("transaction_requests", "contact_phone")
