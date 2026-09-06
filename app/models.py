from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class GroupSpace(Base):
    __tablename__ = "group_spaces"
    __table_args__ = (
        CheckConstraint("lifecycle_status IN ('active','archived','deleted')", name="ck_group_spaces_lifecycle"),
        Index("ix_group_spaces_status_updated", "lifecycle_status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    created_by_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    message_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        UniqueConstraint("space_id", "principal_type", "principal_id", "principal_user_id", name="uq_group_membership_principal"),
        CheckConstraint("role IN ('owner','admin','member')", name="ck_group_membership_role"),
        CheckConstraint("status IN ('active','left','removed')", name="ck_group_membership_status"),
        Index("ix_group_memberships_principal_status", "principal_type", "principal_id", "principal_user_id", "status"),
        Index("ix_group_memberships_space_status", "space_id", "status", "role"),
        Index(
            "uq_group_memberships_active_owner",
            "space_id",
            unique=True,
            sqlite_where=text("status = 'active' AND role = 'owner'"),
            postgresql_where=text("status = 'active' AND role = 'owner'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    principal_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member", server_default="member")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GroupInvitation(Base):
    __tablename__ = "group_invitations"
    __table_args__ = (
        UniqueConstraint("pending_key", name="uq_group_invitation_pending_key"),
        CheckConstraint("target_type IN ('member','business')", name="ck_group_invitations_target_type"),
        CheckConstraint(
            "status IN ('pending','accepted','rejected','cancelled','expired')",
            name="ck_group_invitations_status",
        ),
        Index("ix_group_invitations_space_status", "space_id", "status", "created_at"),
        Index("ix_group_invitations_status_expiry", "status", "expires_at"),
        Index(
            "ix_group_invitations_target_status",
            "target_type",
            "target_id",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_public_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    invited_by_membership_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("group_memberships.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="member", server_default="member"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    pending_key: Mapped[str | None] = mapped_column(String(320))
    accepted_by_user_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", server_default=""
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class GroupMessage(Base):
    __tablename__ = "group_messages"
    __table_args__ = (
        UniqueConstraint("space_id", "sequence", name="uq_group_message_sequence"),
        UniqueConstraint("space_id", "sender_type", "sender_id", "sender_user_id", "client_message_id", name="uq_group_message_client_id"),
        CheckConstraint("source_language IN ('vi','en','zh-TW')", name="ck_group_messages_source_language"),
        CheckConstraint("content_type IN ('text','system','attachment')", name="ck_group_messages_content_type"),
        CheckConstraint("status IN ('active','deleted')", name="ck_group_messages_status"),
        Index("ix_group_messages_space_sequence", "space_id", "sequence"),
        Index("ix_group_messages_reply_to", "reply_to_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sender_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sender_display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    client_message_id: Mapped[str | None] = mapped_column(String(128))
    source_language: Mapped[str] = mapped_column(String(8), nullable=False, default="vi", server_default="vi")
    content_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text", server_default="text")
    content_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_version: Mapped[str] = mapped_column(String(32), nullable=False)
    reply_to_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("group_messages.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GroupChatTranslation(Base):
    __tablename__ = "group_chat_translations"
    __table_args__ = (
        UniqueConstraint(
            "recipient_membership_id",
            "idempotency_key",
            name="uq_group_chat_translation_idempotency",
        ),
        UniqueConstraint(
            "message_id",
            "recipient_membership_id",
            "target_language",
            "message_fingerprint",
            name="uq_group_chat_translation_message_version",
        ),
        CheckConstraint(
            "status IN ('pending','final','failed')",
            name="ck_group_chat_translations_status",
        ),
        CheckConstraint(
            "source_language IN ('vi','en','zh-TW')",
            name="ck_group_chat_translations_source_language",
        ),
        CheckConstraint(
            "target_language IN ('vi','en','zh-TW')",
            name="ck_group_chat_translations_target_language",
        ),
        Index(
            "ix_group_chat_translations_recipient_final",
            "space_id",
            "recipient_membership_id",
            "status",
            "final_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("group_messages.id", ondelete="CASCADE"), nullable=False
    )
    recipient_membership_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("group_memberships.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    message_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_language: Mapped[str] = mapped_column(String(8), nullable=False)
    target_language: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    translated_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    translated_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    encryption_version: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    provider_model: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    provider_request_id: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    failure_code: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    final_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GroupMessageReaction(Base):
    __tablename__ = "group_message_reactions"
    __table_args__ = (
        UniqueConstraint("message_id", "principal_type", "principal_id", "principal_user_id", "reaction", name="uq_group_reaction_actor"),
        Index("ix_group_reactions_message", "message_id", "reaction"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_messages.id", ondelete="CASCADE"), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    principal_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reaction: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GroupMessagePin(Base):
    __tablename__ = "group_message_pins"
    __table_args__ = (
        UniqueConstraint("space_id", "message_id", name="uq_group_pin_message"),
        Index("ix_group_pins_space_created", "space_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_messages.id", ondelete="CASCADE"), nullable=False)
    pinned_by_type: Mapped[str] = mapped_column(String(16), nullable=False)
    pinned_by_id: Mapped[str] = mapped_column(String(128), nullable=False)
    pinned_by_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GroupAttachment(Base):
    __tablename__ = "group_attachments"
    __table_args__ = (
        CheckConstraint("status IN ('pending','attached','deleted')", name="ck_group_attachments_status"),
        Index("ix_group_attachments_space_status", "space_id", "status", "created_at"),
        Index("ix_group_attachments_message", "message_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("group_messages.id", ondelete="SET NULL"))
    uploader_type: Mapped[str] = mapped_column(String(16), nullable=False)
    uploader_id: Mapped[str] = mapped_column(String(128), nullable=False)
    uploader_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GroupAuditEvent(Base):
    __tablename__ = "group_audit_events"
    __table_args__ = (
        Index("ix_group_audit_space_created", "space_id", "created_at", "id"),
        Index("ix_group_audit_actor", "actor_type", "actor_id", "actor_user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    outcome: Mapped[str] = mapped_column(String(24), nullable=False, default="success", server_default="success")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GroupEventOutbox(Base):
    __tablename__ = "group_event_outbox"
    __table_args__ = (
        CheckConstraint("status IN ('pending','published','failed')", name="ck_group_event_outbox_status"),
        Index("ix_group_event_outbox_delivery", "status", "next_attempt_at", "created_at"),
        Index("ix_group_event_outbox_space_created", "space_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_error: Mapped[str] = mapped_column(String(160), nullable=False, default="", server_default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GroupIdempotencyRecord(Base):
    __tablename__ = "group_idempotency_records"
    __table_args__ = (
        UniqueConstraint("endpoint", "actor_key", "idempotency_key", name="uq_group_idempotency_actor"),
        Index("ix_group_idempotency_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_key: Mapped[str] = mapped_column(String(320), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GroupMediaSession(Base):
    __tablename__ = "group_media_sessions"
    __table_args__ = (
        CheckConstraint("media_kind IN ('audio','video')", name="ck_group_media_sessions_kind"),
        CheckConstraint("status IN ('ringing','active','ended')", name="ck_group_media_sessions_status"),
        Index("ix_group_media_sessions_space_status", "space_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    initiated_by_membership_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="RESTRICT"), nullable=False)
    livekit_room_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ringing", server_default="ringing")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_by_membership_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="SET NULL"))
    end_reason: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GroupMediaParticipant(Base):
    __tablename__ = "group_media_participants"
    __table_args__ = (
        UniqueConstraint("session_id", "membership_id", name="uq_group_media_participant_member"),
        UniqueConstraint("session_id", "livekit_identity", name="uq_group_media_participant_identity"),
        CheckConstraint("invite_status IN ('invited','joined','rejected','left')", name="ck_group_media_participants_invite"),
        CheckConstraint(
            "connection_status IN ('not_connected','connecting','connected','reconnecting','failed')",
            name="ck_group_media_participants_connection",
        ),
        Index("ix_group_media_participants_session_status", "session_id", "invite_status"),
        Index("ix_group_media_participants_session_connection", "session_id", "connection_status"),
        Index("ix_group_media_participants_principal", "principal_type", "principal_id", "principal_user_id", "invite_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_media_sessions.id", ondelete="CASCADE"), nullable=False)
    membership_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="RESTRICT"), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    principal_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    livekit_identity: Mapped[str] = mapped_column(String(80), nullable=False)
    invite_status: Mapped[str] = mapped_column(String(16), nullable=False, default="invited", server_default="invited")
    connection_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_connected", server_default="not_connected")
    connection_error_code: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    desired_video_subscriptions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GroupLanguageProfile(Base):
    __tablename__ = "group_language_profiles"
    __table_args__ = (
        UniqueConstraint("space_id", "membership_id", name="uq_group_language_profile_member"),
        Index("ix_group_language_profiles_target", "space_id", "preferred_output_language", "auto_read_enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    membership_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="CASCADE"), nullable=False)
    spoken_language: Mapped[str] = mapped_column(String(8), nullable=False, default="vi", server_default="vi")
    preferred_output_language: Mapped[str] = mapped_column(String(8), nullable=False, default="vi", server_default="vi")
    auto_translate_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    auto_read_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    show_original_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GroupTranslationConsent(Base):
    __tablename__ = "group_translation_consents"
    __table_args__ = (
        UniqueConstraint("space_id", "membership_id", name="uq_group_translation_consent_member"),
        CheckConstraint("status IN ('granted','denied','revoked')", name="ck_group_translation_consents_status"),
        Index("ix_group_translation_consents_space_status", "space_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    membership_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GroupTranslationQuotaLedger(Base):
    __tablename__ = "group_translation_quota_ledgers"
    __table_args__ = (
        UniqueConstraint("billing_subject", "media_kind", "period_start", name="uq_group_translation_quota_period"),
        CheckConstraint("media_kind IN ('audio','video','radio')", name="ck_group_translation_quota_kind"),
        Index("ix_group_translation_quota_subject", "billing_subject", "period_end"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    billing_subject: Mapped[str] = mapped_column(String(160), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    limit_target_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authority_consumed_target_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    consumed_target_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    reserved_target_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    authority: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ai-communication",
        server_default="ai-communication",
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GroupTranslationReservation(Base):
    __tablename__ = "group_translation_reservations"
    __table_args__ = (
        UniqueConstraint("space_id", "runtime_kind", "runtime_id", "segment_id", "target_language", name="uq_group_translation_target_once"),
        UniqueConstraint("actor_key", "idempotency_key", name="uq_group_translation_reservation_idempotency"),
        CheckConstraint("runtime_kind IN ('call','video','radio')", name="ck_group_translation_reservation_runtime"),
        CheckConstraint("status IN ('reserved','settled','released','expired')", name="ck_group_translation_reservation_status"),
        Index("ix_group_translation_reservations_runtime", "runtime_kind", "runtime_id", "status"),
        Index("ix_group_translation_reservations_expiry", "status", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    quota_ledger_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_translation_quota_ledgers.id", ondelete="RESTRICT"), nullable=False)
    payer_membership_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="RESTRICT"), nullable=False)
    actor_key: Mapped[str] = mapped_column(String(320), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    runtime_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    runtime_id: Mapped[str] = mapped_column(String(36), nullable=False)
    segment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_language: Mapped[str] = mapped_column(String(8), nullable=False)
    target_language: Mapped[str] = mapped_column(String(8), nullable=False)
    reserved_target_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    settled_target_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="reserved", server_default="reserved")
    provider_session_id: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    provider_secret_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GroupTranslationEvent(Base):
    __tablename__ = "group_translation_events"
    __table_args__ = (
        UniqueConstraint("reservation_id", name="uq_group_translation_event_reservation"),
        CheckConstraint("state = 'FINAL'", name="ck_group_translation_events_final_only"),
        Index("ix_group_translation_events_runtime", "runtime_kind", "runtime_id", "final_at"),
        Index("ix_group_translation_events_space", "space_id", "final_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reservation_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_translation_reservations.id", ondelete="RESTRICT"), nullable=False)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    speaker_membership_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="RESTRICT"), nullable=False)
    runtime_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    runtime_id: Mapped[str] = mapped_column(String(36), nullable=False)
    segment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_language: Mapped[str] = mapped_column(String(8), nullable=False)
    target_language: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(String(8), nullable=False, default="FINAL", server_default="FINAL")
    original_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    original_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    translated_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    translated_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_version: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_target_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_millis: Mapped[int | None] = mapped_column(Integer)
    final_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GroupTranslationSegment(Base):
    """Canonical source unit for the V2 text-first translation pipeline."""

    __tablename__ = "group_translation_segments"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "runtime_kind", "runtime_id", "speaker_membership_id", "client_segment_id",
            name="uq_group_translation_segment_client",
        ),
        CheckConstraint("runtime_kind IN ('call','video','radio')", name="ck_group_translation_segments_runtime"),
        CheckConstraint("input_kind IN ('text','voice')", name="ck_group_translation_segments_input"),
        CheckConstraint("state IN ('PROCESSING','FINAL','PARTIAL','FAILED')", name="ck_group_translation_segments_state"),
        Index("ix_group_translation_segments_runtime", "space_id", "runtime_kind", "runtime_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_segment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    runtime_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    runtime_id: Mapped[str] = mapped_column(String(36), nullable=False)
    speaker_membership_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="RESTRICT"), nullable=False)
    input_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    source_language: Mapped[str] = mapped_column(String(8), nullable=False)
    source_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    source_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_version: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="PROCESSING", server_default="PROCESSING")
    failure_code: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GroupTranslationVariant(Base):
    """One encrypted translated variant per target language."""

    __tablename__ = "group_translation_variants"
    __table_args__ = (
        UniqueConstraint("segment_id", "target_language", name="uq_group_translation_variant_target"),
        CheckConstraint("state IN ('PROCESSING','FINAL','FAILED')", name="ck_group_translation_variants_state"),
        Index("ix_group_translation_variants_segment_state", "segment_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    segment_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_translation_segments.id", ondelete="CASCADE"), nullable=False)
    target_language: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="PROCESSING", server_default="PROCESSING")
    translated_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    translated_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    encryption_version: Mapped[str | None] = mapped_column(String(32))
    provider_model: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    provider_request_id: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    failure_code: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GroupTtsJob(Base):
    __tablename__ = "group_tts_jobs"
    __table_args__ = (
        UniqueConstraint("translation_event_id", "recipient_membership_id", name="uq_group_tts_event_recipient"),
        CheckConstraint("status IN ('pending','claimed','completed','failed','suppressed')", name="ck_group_tts_jobs_status"),
        Index("ix_group_tts_recipient_status", "recipient_membership_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    translation_event_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_translation_events.id", ondelete="CASCADE"), nullable=False)
    recipient_membership_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="CASCADE"), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    auto_read_snapshot: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GroupRadioSession(Base):
    __tablename__ = "group_radio_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('ready','ended')", name="ck_group_radio_sessions_status"),
        Index("ix_group_radio_sessions_space_status", "space_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    created_by_membership_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="RESTRICT"), nullable=False)
    livekit_room_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready", server_default="ready")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    ended_by_membership_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="SET NULL"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GroupRadioParticipant(Base):
    __tablename__ = "group_radio_participants"
    __table_args__ = (
        UniqueConstraint("radio_session_id", "membership_id", name="uq_group_radio_participant_member"),
        UniqueConstraint("radio_session_id", "livekit_identity", name="uq_group_radio_participant_identity"),
        CheckConstraint("status IN ('invited','joined','left','removed')", name="ck_group_radio_participants_status"),
        CheckConstraint("device_state IN ('ready','lost')", name="ck_group_radio_participants_device"),
        Index("ix_group_radio_participants_session_status", "radio_session_id", "status"),
        Index("ix_group_radio_participants_principal", "principal_type", "principal_id", "principal_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    radio_session_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_radio_sessions.id", ondelete="CASCADE"), nullable=False)
    membership_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="RESTRICT"), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    principal_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    livekit_identity: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="invited", server_default="invited")
    device_state: Mapped[str] = mapped_column(String(16), nullable=False, default="ready", server_default="ready")
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device_lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GroupRadioBurst(Base):
    __tablename__ = "group_radio_bursts"
    __table_args__ = (
        CheckConstraint("state IN ('talking','finalizing','final','device_lost','failed')", name="ck_group_radio_bursts_state"),
        Index("ix_group_radio_bursts_session_created", "radio_session_id", "created_at"),
        Index("ix_group_radio_bursts_state", "state", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    radio_session_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_radio_sessions.id", ondelete="CASCADE"), nullable=False)
    space_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_spaces.id", ondelete="CASCADE"), nullable=False)
    speaker_participant_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_radio_participants.id", ondelete="RESTRICT"), nullable=False)
    speaker_membership_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_memberships.id", ondelete="RESTRICT"), nullable=False)
    floor_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="talking", server_default="talking")
    source_language: Mapped[str] = mapped_column(String(8), nullable=False, default="vi", server_default="vi")
    target_languages_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    stop_reason: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class GroupRadioProcessingJob(Base):
    __tablename__ = "group_radio_processing_jobs"
    __table_args__ = (
        UniqueConstraint("burst_id", name="uq_group_radio_processing_burst"),
        CheckConstraint("status IN ('ready','processing','completed','failed','suppressed')", name="ck_group_radio_processing_status"),
        Index("ix_group_radio_processing_status", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    burst_id: Mapped[str] = mapped_column(String(36), ForeignKey("group_radio_bursts.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready", server_default="ready")
    failure_code: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
