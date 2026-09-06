"""canonical text-first Group Translation V2 segments and variants

Revision ID: 20260904_0023
Revises: 20260904_0022
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260904_0023"
down_revision = "20260904_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_translation_segments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_segment_id", sa.String(128), nullable=False),
        sa.Column("space_id", sa.String(36), sa.ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("runtime_kind", sa.String(16), nullable=False),
        sa.Column("runtime_id", sa.String(36), nullable=False),
        sa.Column("speaker_membership_id", sa.String(36), sa.ForeignKey("group_memberships.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("input_kind", sa.String(8), nullable=False),
        sa.Column("source_language", sa.String(8), nullable=False),
        sa.Column("source_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("source_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_version", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="PROCESSING"),
        sa.Column("failure_code", sa.String(80), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("space_id", "runtime_kind", "runtime_id", "speaker_membership_id", "client_segment_id", name="uq_group_translation_segment_client"),
        sa.CheckConstraint("runtime_kind IN ('call','video','radio')", name="ck_group_translation_segments_runtime"),
        sa.CheckConstraint("input_kind IN ('text','voice')", name="ck_group_translation_segments_input"),
        sa.CheckConstraint("state IN ('PROCESSING','FINAL','PARTIAL','FAILED')", name="ck_group_translation_segments_state"),
    )
    op.create_index("ix_group_translation_segments_runtime", "group_translation_segments", ["space_id", "runtime_kind", "runtime_id", "created_at"])
    op.create_table(
        "group_translation_variants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("segment_id", sa.String(36), sa.ForeignKey("group_translation_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_language", sa.String(8), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="PROCESSING"),
        sa.Column("translated_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("translated_nonce", sa.LargeBinary(), nullable=True),
        sa.Column("encryption_version", sa.String(32), nullable=True),
        sa.Column("provider_model", sa.String(80), nullable=False, server_default=""),
        sa.Column("provider_request_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("failure_code", sa.String(80), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("segment_id", "target_language", name="uq_group_translation_variant_target"),
        sa.CheckConstraint("state IN ('PROCESSING','FINAL','FAILED')", name="ck_group_translation_variants_state"),
    )
    op.create_index("ix_group_translation_variants_segment_state", "group_translation_variants", ["segment_id", "state"])


def downgrade() -> None:
    op.drop_index("ix_group_translation_variants_segment_state", table_name="group_translation_variants")
    op.drop_table("group_translation_variants")
    op.drop_index("ix_group_translation_segments_runtime", table_name="group_translation_segments")
    op.drop_table("group_translation_segments")
