"""email replies

Revision ID: 20260618_0002
Revises: 20260618_0001
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260618_0002"
down_revision = "20260618_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_replies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sender", sa.String(length=255), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("raw_payload", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("is_processed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["transaction_requests.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_email_replies_provider_message_id"), "email_replies", ["provider_message_id"], unique=False)
    op.create_index(op.f("ix_email_replies_sender"), "email_replies", ["sender"], unique=False)
    op.create_index(op.f("ix_email_replies_user_id"), "email_replies", ["user_id"], unique=False)
    op.create_index(op.f("ix_email_replies_transaction_id"), "email_replies", ["transaction_id"], unique=False)
    op.create_index(op.f("ix_email_replies_is_processed"), "email_replies", ["is_processed"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_email_replies_is_processed"), table_name="email_replies")
    op.drop_index(op.f("ix_email_replies_transaction_id"), table_name="email_replies")
    op.drop_index(op.f("ix_email_replies_user_id"), table_name="email_replies")
    op.drop_index(op.f("ix_email_replies_sender"), table_name="email_replies")
    op.drop_index(op.f("ix_email_replies_provider_message_id"), table_name="email_replies")
    op.drop_table("email_replies")
