"""shared chat translation and durable Group notifications

Revision ID: 20260907_0024
Revises: 20260904_0023
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260907_0024"
down_revision = "20260904_0023"
branch_labels = None
depends_on = None


_FK_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _foreign_key_name(table_name: str, column_name: str, referred_table: str) -> str:
    """Return a reflected FK name, including a stable name for SQLite's unnamed FK."""

    for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table_name):
        if (
            foreign_key.get("constrained_columns") == [column_name]
            and foreign_key.get("referred_table") == referred_table
        ):
            return foreign_key.get("name") or (
                f"fk_{table_name}_{column_name}_{referred_table}"
            )
    raise RuntimeError(
        f"missing foreign key {table_name}.{column_name} -> {referred_table}"
    )


def _create_translation_archive() -> None:
    """Retain the exact legacy table contents for audit and downgrade."""
    op.create_table(
        "group_chat_translation_legacy_archive",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("group_spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("group_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipient_membership_id",
            sa.String(36),
            sa.ForeignKey("group_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("message_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_language", sa.String(8), nullable=False),
        sa.Column("target_language", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("translated_ciphertext", sa.LargeBinary()),
        sa.Column("translated_nonce", sa.LargeBinary()),
        sa.Column("encryption_version", sa.String(32), nullable=False),
        sa.Column("provider_model", sa.String(80), nullable=False),
        sa.Column("provider_request_id", sa.String(128), nullable=False),
        sa.Column("failure_code", sa.String(80), nullable=False),
        sa.Column("final_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "archived_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute(
        """
        INSERT INTO group_chat_translation_legacy_archive (
            id, space_id, message_id, recipient_membership_id, idempotency_key,
            message_fingerprint, source_language, target_language, status,
            translated_ciphertext, translated_nonce, encryption_version,
            provider_model, provider_request_id, failure_code, final_at,
            created_at, updated_at
        )
        SELECT
            id, space_id, message_id, recipient_membership_id, idempotency_key,
            message_fingerprint, source_language, target_language, status,
            translated_ciphertext, translated_nonce, encryption_version,
            provider_model, provider_request_id, failure_code, final_at,
            created_at, updated_at
        FROM group_chat_translations
        """
    )


def upgrade() -> None:
    with op.batch_alter_table("group_memberships") as batch:
        batch.add_column(
            sa.Column("notification_mode", sa.String(16), nullable=False, server_default="smart")
        )
        batch.add_column(sa.Column("notification_muted_until", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column("notification_paused", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("last_seen_sequence", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("unread_count", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch.create_check_constraint(
            "ck_group_membership_notification_mode",
            "notification_mode IN ('smart','all','important','none')",
        )
        batch.create_check_constraint(
            "ck_group_membership_notification_paused",
            "notification_paused IN (0,1)",
        )

    with op.batch_alter_table("group_event_outbox") as batch:
        batch.add_column(
            sa.Column(
                "notification_status",
                sa.String(16),
                nullable=False,
                server_default="completed",
            )
        )
        batch.add_column(
            sa.Column("notification_attempts", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column(
                "notification_next_attempt_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.add_column(
            sa.Column("notification_last_error", sa.String(160), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("notification_dispatched_at", sa.DateTime(timezone=True)))
        batch.create_check_constraint(
            "ck_group_event_outbox_notification_status",
            "notification_status IN ('pending','processing','completed','failed')",
        )
        batch.create_index(
            "ix_group_event_outbox_notification",
            ["notification_status", "notification_next_attempt_at", "created_at"],
        )
    with op.batch_alter_table("group_event_outbox") as batch:
        batch.alter_column(
            "notification_status",
            existing_type=sa.String(16),
            existing_nullable=False,
            server_default="pending",
        )

    with op.batch_alter_table("group_language_profiles") as batch:
        batch.add_column(
            sa.Column(
                "chat_auto_translate_enabled",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )

    _create_translation_archive()
    op.execute(
        """
        DELETE FROM group_chat_translations
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY message_id, message_fingerprint, target_language
                    ORDER BY
                        CASE status WHEN 'final' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,
                        final_at ASC,
                        created_at ASC,
                        id ASC
                ) AS duplicate_rank
                FROM group_chat_translations
            ) AS ranked
            WHERE duplicate_rank > 1
        )
        """
    )

    # Keep the legacy physical recipient column for rolling-process
    # compatibility. From this revision onward it is an immutable cost-owner
    # snapshot, so it must no longer cascade with membership lifecycle.
    membership_foreign_key = _foreign_key_name(
        "group_chat_translations", "recipient_membership_id", "group_memberships"
    )
    with op.batch_alter_table(
        "group_chat_translations", naming_convention=_FK_NAMING_CONVENTION
    ) as batch:
        batch.drop_index("ix_group_chat_translations_recipient_final")
        batch.drop_constraint("uq_group_chat_translation_idempotency", type_="unique")
        batch.drop_constraint("uq_group_chat_translation_message_version", type_="unique")
        batch.drop_constraint(membership_foreign_key, type_="foreignkey")
        batch.add_column(sa.Column("cost_state", sa.String(16)))
        batch.add_column(
            sa.Column("claim_token", sa.String(64), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.execute(
        """
        UPDATE group_chat_translations
        SET cost_state = CASE WHEN status = 'final' THEN 'settled' ELSE 'released' END
        """
    )
    with op.batch_alter_table("group_chat_translations") as batch:
        batch.alter_column(
            "cost_state",
            existing_type=sa.String(16),
            nullable=False,
            server_default="reserved",
        )
        batch.create_unique_constraint(
            "uq_group_chat_translation_shared_variant",
            ["message_id", "message_fingerprint", "target_language"],
        )
        batch.create_check_constraint(
            "ck_group_chat_translations_cost_state",
            "cost_state IN ('reserved','settled','released')",
        )
        batch.create_index(
            "ix_group_chat_translations_shared_final",
            ["space_id", "target_language", "status", "final_at"],
        )

    op.create_table(
        "group_chat_translation_cost_ledgers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("billing_subject", sa.String(160), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("limit_variant_units", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved_variant_units", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("settled_variant_units", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "authority", sa.String(32), nullable=False, server_default="ai-communication"
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "billing_subject", "period_start", name="uq_group_chat_translation_cost_period"
        ),
    )
    op.create_index(
        "ix_group_chat_translation_cost_subject",
        "group_chat_translation_cost_ledgers",
        ["billing_subject", "period_end"],
    )

    op.create_table(
        "group_chat_translation_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "translation_id",
            sa.String(36),
            sa.ForeignKey("group_chat_translations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requester_membership_id",
            sa.String(36),
            nullable=False,
        ),
        sa.Column(
            "cost_ledger_id",
            sa.String(36),
            sa.ForeignKey("group_chat_translation_cost_ledgers.id", ondelete="RESTRICT"),
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("cost_state", sa.String(16), nullable=False, server_default="reuse"),
        sa.Column("claim_token", sa.String(64), nullable=False, server_default=""),
        sa.Column("reserved_variant_units", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("settled_variant_units", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "requester_membership_id",
            "idempotency_key",
            name="uq_group_chat_translation_request_idempotency",
        ),
        sa.CheckConstraint(
            "cost_state IN ('reuse','reserved','settled','released')",
            name="ck_group_chat_translation_requests_cost_state",
        ),
    )
    op.create_index(
        "ix_group_chat_translation_requests_variant",
        "group_chat_translation_requests",
        ["translation_id", "cost_state", "created_at"],
    )
    op.execute(
        """
        INSERT INTO group_chat_translation_requests (
            id, translation_id, requester_membership_id, idempotency_key,
            cost_state, settled_variant_units, created_at, updated_at
        )
        SELECT
            id, id, recipient_membership_id, idempotency_key,
            CASE WHEN status = 'final' THEN 'settled' ELSE 'released' END,
            CASE WHEN status = 'final' THEN 1 ELSE 0 END,
            created_at, updated_at
        FROM group_chat_translations
        """
    )

    op.create_table(
        "group_notification_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "group_event_id",
            sa.String(36),
            sa.ForeignKey("group_event_outbox.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("group_spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_id", sa.String(80), nullable=False, server_default=""),
        sa.Column(
            "recipient_membership_id",
            sa.String(36),
            sa.ForeignKey("group_memberships.id", ondelete="CASCADE"),
        ),
        sa.Column("recipient_type", sa.String(16), nullable=False),
        sa.Column("recipient_id", sa.String(128), nullable=False),
        sa.Column("recipient_user_id", sa.String(128), nullable=False),
        sa.Column("notification_class", sa.String(40), nullable=False),
        sa.Column("event_kind", sa.String(80), nullable=False),
        sa.Column("push_eligible", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_error", sa.String(160), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "group_event_id",
            "recipient_type",
            "recipient_id",
            "recipient_user_id",
            "notification_class",
            name="uq_group_notification_semantic_delivery",
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing','delivered','suppressed','failed')",
            name="ck_group_notification_deliveries_status",
        ),
    )
    op.create_index(
        "ix_group_notification_deliveries_dispatch",
        "group_notification_deliveries",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_group_notification_deliveries_recipient",
        "group_notification_deliveries",
        ["recipient_type", "recipient_id", "recipient_user_id", "created_at"],
    )

def downgrade() -> None:
    with op.batch_alter_table("group_language_profiles") as batch:
        batch.drop_column("chat_auto_translate_enabled")

    op.drop_index(
        "ix_group_notification_deliveries_recipient", table_name="group_notification_deliveries"
    )
    op.drop_index(
        "ix_group_notification_deliveries_dispatch", table_name="group_notification_deliveries"
    )
    op.drop_table("group_notification_deliveries")
    op.drop_index(
        "ix_group_chat_translation_requests_variant",
        table_name="group_chat_translation_requests",
    )
    op.drop_table("group_chat_translation_requests")
    op.drop_index(
        "ix_group_chat_translation_cost_subject",
        table_name="group_chat_translation_cost_ledgers",
    )
    op.drop_table("group_chat_translation_cost_ledgers")

    with op.batch_alter_table("group_chat_translations") as batch:
        batch.drop_index("ix_group_chat_translations_shared_final")
        batch.drop_constraint("ck_group_chat_translations_cost_state", type_="check")
        batch.drop_constraint("uq_group_chat_translation_shared_variant", type_="unique")
        batch.drop_column("lease_expires_at")
        batch.drop_column("claim_token")
        batch.drop_column("cost_state")
    # Rows that existed before upgrade are restored byte-for-byte, including
    # their original IDs so encrypted AAD remains valid. Remove only rows whose
    # parents no longer exist: those rows cannot be represented by the legacy
    # foreign-key schema after downgrade.
    op.execute(
        """
        DELETE FROM group_chat_translations
        WHERE NOT EXISTS (
            SELECT 1 FROM group_spaces
            WHERE group_spaces.id = group_chat_translations.space_id
        )
        OR NOT EXISTS (
            SELECT 1 FROM group_messages
            WHERE group_messages.id = group_chat_translations.message_id
        )
        OR NOT EXISTS (
            SELECT 1 FROM group_memberships
            WHERE group_memberships.id = group_chat_translations.recipient_membership_id
        )
        """
    )
    op.execute(
        """
        DELETE FROM group_chat_translations
        WHERE id IN (SELECT id FROM group_chat_translation_legacy_archive)
        """
    )
    op.execute(
        """
        INSERT INTO group_chat_translations (
            id, space_id, message_id, recipient_membership_id, idempotency_key,
            message_fingerprint, source_language, target_language, status,
            translated_ciphertext, translated_nonce, encryption_version,
            provider_model, provider_request_id, failure_code, final_at,
            created_at, updated_at
        )
        SELECT
            id, space_id, message_id, recipient_membership_id, idempotency_key,
            message_fingerprint, source_language, target_language, status,
            translated_ciphertext, translated_nonce, encryption_version,
            provider_model, provider_request_id, failure_code, final_at,
            created_at, updated_at
        FROM group_chat_translation_legacy_archive AS archive
        WHERE EXISTS (
            SELECT 1 FROM group_spaces WHERE group_spaces.id = archive.space_id
        )
        AND EXISTS (
            SELECT 1 FROM group_messages WHERE group_messages.id = archive.message_id
        )
        AND EXISTS (
            SELECT 1 FROM group_memberships
            WHERE group_memberships.id = archive.recipient_membership_id
        )
        """
    )
    with op.batch_alter_table("group_chat_translations") as batch:
        batch.create_foreign_key(
            "fk_group_chat_translations_recipient_membership_id_group_memberships",
            "group_memberships",
            ["recipient_membership_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint(
            "uq_group_chat_translation_idempotency",
            ["recipient_membership_id", "idempotency_key"],
        )
        batch.create_unique_constraint(
            "uq_group_chat_translation_message_version",
            [
                "message_id",
                "recipient_membership_id",
                "target_language",
                "message_fingerprint",
            ],
        )
        batch.create_index(
            "ix_group_chat_translations_recipient_final",
            ["space_id", "recipient_membership_id", "status", "final_at"],
        )
    op.drop_table("group_chat_translation_legacy_archive")

    with op.batch_alter_table("group_memberships") as batch:
        batch.drop_constraint("ck_group_membership_notification_paused", type_="check")
        batch.drop_constraint("ck_group_membership_notification_mode", type_="check")
        batch.drop_column("unread_count")
        batch.drop_column("last_seen_sequence")
        batch.drop_column("notification_paused")
        batch.drop_column("notification_muted_until")
        batch.drop_column("notification_mode")

    with op.batch_alter_table("group_event_outbox") as batch:
        batch.drop_index("ix_group_event_outbox_notification")
        batch.drop_constraint("ck_group_event_outbox_notification_status", type_="check")
        batch.drop_column("notification_dispatched_at")
        batch.drop_column("notification_last_error")
        batch.drop_column("notification_next_attempt_at")
        batch.drop_column("notification_attempts")
        batch.drop_column("notification_status")
