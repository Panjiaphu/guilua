"""rate reference mode

Revision ID: 20260619_0005
Revises: 20260619_0004
Create Date: 2026-06-19 10:40:00.000000

"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


revision = "20260619_0005"
down_revision = "20260619_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    exchange_rates = sa.table(
        "exchange_rates",
        sa.column("pair", sa.String),
        sa.column("buy_rate", sa.Numeric),
        sa.column("sell_rate", sa.Numeric),
        sa.column("source", sa.String),
        sa.column("is_manual", sa.Boolean),
        sa.column("note", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        exchange_rates,
        [
            {
                "pair": "TWD_VND",
                "buy_rate": 824.000000,
                "sell_rate": 818.000000,
                "source": "manual",
                "is_manual": True,
                "note": "Admin rate board",
                "created_at": now,
                "updated_at": now,
            },
            {
                "pair": "USDT_TWD",
                "buy_rate": 31.920000,
                "sell_rate": 31.520000,
                "source": "manual",
                "is_manual": True,
                "note": "Admin rate board",
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM exchange_rates WHERE note = 'Admin rate board'")
