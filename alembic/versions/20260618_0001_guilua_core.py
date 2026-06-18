"""guilua core schema

Revision ID: 20260618_0001
Revises:
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260618_0001"
down_revision = None
branch_labels = None
depends_on = None


transaction_type = sa.Enum("SEND_HOME", "BUY_USDT", "SELL_USDT", name="transactiontype")
transaction_status = sa.Enum(
    "PENDING",
    "IN_REVIEW",
    "NEEDS_INFO",
    "APPROVED",
    "COMPLETED",
    "REJECTED",
    "CANCELLED",
    name="transactionstatus",
)
email_status = sa.Enum("QUEUED", "SENT", "FAILED", name="emailstatus")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("locale", sa.String(length=12), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_email_verified", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)

    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pair", sa.String(length=32), nullable=False),
        sa.Column("buy_rate", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("sell_rate", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("is_manual", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exchange_rates_pair"), "exchange_rates", ["pair"], unique=False)
    op.create_index("ix_exchange_rates_pair_updated", "exchange_rates", ["pair", "updated_at"], unique=False)

    op.create_table(
        "transaction_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference_code", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("request_type", transaction_type, nullable=False),
        sa.Column("status", transaction_status, nullable=False),
        sa.Column("amount_twd", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("amount_vnd", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("amount_usdt", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("rate_pair", sa.String(length=32), nullable=False),
        sa.Column("rate_value", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("recipient_name", sa.String(length=120), nullable=False),
        sa.Column("recipient_bank", sa.String(length=120), nullable=False),
        sa.Column("recipient_account", sa.String(length=120), nullable=False),
        sa.Column("member_note", sa.Text(), nullable=False),
        sa.Column("admin_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference_code"),
    )
    op.create_index(op.f("ix_transaction_requests_reference_code"), "transaction_requests", ["reference_code"], unique=False)
    op.create_index(op.f("ix_transaction_requests_request_type"), "transaction_requests", ["request_type"], unique=False)
    op.create_index(op.f("ix_transaction_requests_status"), "transaction_requests", ["status"], unique=False)
    op.create_index(op.f("ix_transaction_requests_user_id"), "transaction_requests", ["user_id"], unique=False)

    op.create_table(
        "email_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", email_status, nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["transaction_id"], ["transaction_requests.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_email_notifications_event_type"), "email_notifications", ["event_type"], unique=False)
    op.create_index(op.f("ix_email_notifications_recipient"), "email_notifications", ["recipient"], unique=False)
    op.create_index(op.f("ix_email_notifications_status"), "email_notifications", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_email_notifications_status"), table_name="email_notifications")
    op.drop_index(op.f("ix_email_notifications_recipient"), table_name="email_notifications")
    op.drop_index(op.f("ix_email_notifications_event_type"), table_name="email_notifications")
    op.drop_table("email_notifications")
    op.drop_index(op.f("ix_transaction_requests_user_id"), table_name="transaction_requests")
    op.drop_index(op.f("ix_transaction_requests_status"), table_name="transaction_requests")
    op.drop_index(op.f("ix_transaction_requests_request_type"), table_name="transaction_requests")
    op.drop_index(op.f("ix_transaction_requests_reference_code"), table_name="transaction_requests")
    op.drop_table("transaction_requests")
    op.drop_index("ix_exchange_rates_pair_updated", table_name="exchange_rates")
    op.drop_index(op.f("ix_exchange_rates_pair"), table_name="exchange_rates")
    op.drop_table("exchange_rates")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    email_status.drop(op.get_bind(), checkfirst=True)
    transaction_status.drop(op.get_bind(), checkfirst=True)
    transaction_type.drop(op.get_bind(), checkfirst=True)
