from __future__ import annotations

import json
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db import Database
from app.group_v3.auth import GroupActor
from app.group_v3.crypto import GroupCrypto
from app.group_v3.service import GroupServiceError
from app.models import (
    GroupAuditEvent,
    GroupLanguageProfile,
    GroupMediaParticipant,
    GroupMediaSession,
    GroupMembership,
    GroupRadioBurst,
    GroupRadioParticipant,
    GroupRadioProcessingJob,
    GroupRadioSession,
    GroupTranslationConsent,
    GroupTranslationEvent,
    GroupTranslationQuotaLedger,
    GroupTranslationReservation,
    GroupTranslationSegment,
    GroupTranslationVariant,
    GroupTtsJob,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


class GroupTranslationService:
    def __init__(self, database: Database, settings: Settings, crypto: GroupCrypto, provider=None, event_broker=None):
        self.database = database
        self.settings = settings
        self.crypto = crypto
        self.provider = provider
        self.event_broker = event_broker
        # Gunicorn runs one worker for this service.  Serialize duplicate voice
        # submissions per canonical client id so the provider STT request is
        # issued once even when the browser retries before the first response.
        self._voice_locks: dict[str, asyncio.Lock] = {}
        # The deployed service uses one Gunicorn worker.  Serialize provider
        # work by the canonical shared variant identity so two recipients
        # cannot translate the same missing historical language twice.
        self._variant_locks: dict[str, asyncio.Lock] = {}

    def set_runtime_dependencies(self, provider=None, event_broker=None) -> None:
        """Allow application startup to wire the provider after construction."""
        if provider is not None:
            self.provider = provider
        if event_broker is not None:
            self.event_broker = event_broker

    @staticmethod
    def _membership(db, space_id: str, actor: GroupActor) -> GroupMembership:
        membership = db.scalar(
            select(GroupMembership).where(
                GroupMembership.space_id == space_id,
                GroupMembership.principal_type == actor.principal_type,
                GroupMembership.principal_id == actor.principal_id,
                GroupMembership.principal_user_id == actor.principal_user_id,
                GroupMembership.status == "active",
            )
        )
        if not membership:
            raise GroupServiceError("group_membership_required", 403)
        return membership

    @staticmethod
    def _membership_actor_key(membership: GroupMembership) -> str:
        return ":".join((
            str(membership.principal_type),
            str(membership.principal_id),
            str(membership.principal_user_id),
        ))

    @staticmethod
    def _audit(db, actor: GroupActor, space_id: str, event_type: str, resource_type: str, resource_id: str, metadata: dict | None = None) -> None:
        db.add(
            GroupAuditEvent(
                id=str(uuid4()),
                space_id=space_id,
                actor_type=actor.principal_type,
                actor_id=actor.principal_id,
                actor_user_id=actor.principal_user_id,
                event_type=event_type,
                resource_type=resource_type,
                resource_id=resource_id,
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            )
        )

    @staticmethod
    def _profile_payload(item: GroupLanguageProfile) -> dict:
        return {
            "spoken_language": item.spoken_language,
            "preferred_output_language": item.preferred_output_language,
            "auto_translate_enabled": bool(item.auto_translate_enabled),
            "chat_auto_translate_enabled": bool(item.chat_auto_translate_enabled),
            "auto_read_enabled": bool(item.auto_read_enabled),
            "show_original_enabled": bool(item.show_original_enabled),
            "updated_at": _iso(item.updated_at),
        }

    def _effective_language_profile(
        self,
        db,
        membership: GroupMembership,
        source_language: str,
        actor: GroupActor | None = None,
        profile: GroupLanguageProfile | None = None,
    ) -> dict:
        """Resolve one profile for every joined member without silent drops.

        Membership rows do not duplicate the account locale.  Until a member
        saves Translation settings, the deterministic fallback is the current
        segment's canonical source language. Routing, projections and counts
        all use this same resolver.
        """
        if profile is None:
            profile = db.scalar(select(GroupLanguageProfile).where(
                GroupLanguageProfile.space_id == membership.space_id,
                GroupLanguageProfile.membership_id == membership.id,
            ))
        if profile:
            spoken = profile.spoken_language if profile.spoken_language in {"vi", "en", "zh-TW"} else source_language
            preferred = profile.preferred_output_language if profile.preferred_output_language in {"vi", "en", "zh-TW"} else source_language
            return {
                "spoken_language": spoken,
                "preferred_output_language": preferred,
                "auto_translate_enabled": bool(profile.auto_translate_enabled),
                "chat_auto_translate_enabled": bool(profile.chat_auto_translate_enabled),
                "auto_read_enabled": bool(profile.auto_read_enabled),
                "show_original_enabled": bool(profile.show_original_enabled),
                "profile_source": "stored",
            }
        # The fallback is deliberately the same for the speaker and every
        # recipient: routing cannot read an external account locale from a
        # membership row, so using actor.locale only in projection would make
        # a missing-profile member disappear from its own variant.
        fallback = source_language
        return {
            "spoken_language": fallback,
            "preferred_output_language": fallback,
            "auto_translate_enabled": True,
            "chat_auto_translate_enabled": False,
            "auto_read_enabled": False,
            "show_original_enabled": True,
            "profile_source": "fallback",
        }

    def get_profile(self, actor: GroupActor, space_id: str) -> dict:
        with self.database.session() as db:
            with db.begin():
                membership = self._membership(db, space_id, actor)
                profile = db.scalar(select(GroupLanguageProfile).where(GroupLanguageProfile.space_id == space_id, GroupLanguageProfile.membership_id == membership.id))
                if not profile:
                    profile = GroupLanguageProfile(
                        id=str(uuid4()),
                        space_id=space_id,
                        membership_id=membership.id,
                        spoken_language=actor.locale,
                        preferred_output_language=actor.locale,
                        auto_translate_enabled=1,
                        chat_auto_translate_enabled=0,
                        auto_read_enabled=0,
                        show_original_enabled=1,
                    )
                    db.add(profile)
                    self._audit(
                        db,
                        actor,
                        space_id,
                        "translation.profile_initialized",
                        "language_profile",
                        profile.id,
                    )
                return self._profile_payload(profile)

    def update_profile(self, actor: GroupActor, space_id: str, values: dict) -> dict:
        with self.database.session() as db:
            with db.begin():
                membership = self._membership(db, space_id, actor)
                profile = db.scalar(select(GroupLanguageProfile).where(GroupLanguageProfile.space_id == space_id, GroupLanguageProfile.membership_id == membership.id))
                if not profile:
                    profile = GroupLanguageProfile(id=str(uuid4()), space_id=space_id, membership_id=membership.id)
                    db.add(profile)
                profile.spoken_language = values["spoken_language"]
                profile.preferred_output_language = values["preferred_output_language"]
                profile.auto_translate_enabled = int(values["auto_translate_enabled"])
                profile.chat_auto_translate_enabled = int(
                    values["chat_auto_translate_enabled"]
                )
                profile.auto_read_enabled = int(values["auto_read_enabled"])
                profile.show_original_enabled = int(values["show_original_enabled"])
                profile.updated_at = _now()
                self._audit(db, actor, space_id, "translation.profile_updated", "language_profile", profile.id)
                return self._profile_payload(profile)

    def get_consent(self, actor: GroupActor, space_id: str) -> dict:
        with self.database.session() as db:
            membership = self._membership(db, space_id, actor)
            consent = db.scalar(select(GroupTranslationConsent).where(GroupTranslationConsent.space_id == space_id, GroupTranslationConsent.membership_id == membership.id))
            return {
                "status": consent.status if consent else "not_set",
                "policy_version": consent.policy_version if consent else self.settings.group_translation_policy_version,
                "decided_at": _iso(consent.decided_at) if consent else None,
            }

    def update_consent(self, actor: GroupActor, space_id: str, status: str, policy_version: str) -> dict:
        if policy_version != self.settings.group_translation_policy_version:
            raise GroupServiceError("group_translation_policy_version_mismatch", 409)
        with self.database.session() as db:
            with db.begin():
                membership = self._membership(db, space_id, actor)
                consent = db.scalar(select(GroupTranslationConsent).where(GroupTranslationConsent.space_id == space_id, GroupTranslationConsent.membership_id == membership.id))
                if not consent:
                    consent = GroupTranslationConsent(id=str(uuid4()), space_id=space_id, membership_id=membership.id, status=status, policy_version=policy_version, decided_at=_now())
                    db.add(consent)
                else:
                    consent.status = status
                    consent.policy_version = policy_version
                    consent.decided_at = _now()
                    consent.updated_at = _now()
                self._audit(db, actor, space_id, "translation.consent_updated", "translation_consent", consent.id, {"status": status, "policy_version": policy_version})
                return {"status": consent.status, "policy_version": consent.policy_version, "decided_at": _iso(consent.decided_at)}

    def _sync_ledger(self, db, actor: GroupActor, media_kind: str) -> GroupTranslationQuotaLedger:
        now = _now()
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if period_start.month == 12:
            period_end = period_start.replace(year=period_start.year + 1, month=1)
        else:
            period_end = period_start.replace(month=period_start.month + 1)
        ledger_kind = "video" if media_kind == "video" else "audio"
        limit_seconds = (
            self.settings.group_translation_monthly_video_target_seconds
            if ledger_kind == "video"
            else self.settings.group_translation_monthly_audio_target_seconds
        )
        billing_subject = actor.key[:160]
        ledger = db.scalar(
            select(GroupTranslationQuotaLedger)
            .where(
                GroupTranslationQuotaLedger.billing_subject == billing_subject,
                GroupTranslationQuotaLedger.media_kind == ledger_kind,
                GroupTranslationQuotaLedger.period_start == period_start,
            )
            .with_for_update()
        )
        if not ledger:
            ledger = GroupTranslationQuotaLedger(
                id=str(uuid4()),
                billing_subject=billing_subject,
                media_kind=ledger_kind,
                period_start=period_start,
                period_end=period_end,
                limit_target_seconds=limit_seconds,
                authority_consumed_target_seconds=0,
                authority="ai-communication",
            )
            db.add(ledger)
            db.flush()
        else:
            if ledger.authority != "ai-communication":
                raise GroupServiceError(
                    "group_translation_legacy_ledger_audit_required", 409
                )
            ledger.period_end = period_end
            ledger.limit_target_seconds = limit_seconds
            ledger.authority_consumed_target_seconds = 0
            ledger.updated_at = _now()
        return ledger

    @staticmethod
    def _quota_payload(ledger: GroupTranslationQuotaLedger) -> dict:
        unavailable = ledger.authority_consumed_target_seconds + ledger.consumed_target_seconds + ledger.reserved_target_seconds
        return {
            "authority": ledger.authority,
            "media_kind": ledger.media_kind,
            "period_start": _iso(ledger.period_start),
            "period_end": _iso(ledger.period_end),
            "limit_target_seconds": ledger.limit_target_seconds,
            "authority_consumed_target_seconds": ledger.authority_consumed_target_seconds,
            "consumed_target_seconds": ledger.consumed_target_seconds,
            "reserved_target_seconds": ledger.reserved_target_seconds,
            "remaining_target_seconds": max(0, ledger.limit_target_seconds - unavailable),
        }

    def quota(self, actor: GroupActor, space_id: str, media_kind: str) -> dict:
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                ledger = self._sync_ledger(db, actor, media_kind)
                return self._quota_payload(ledger)

    def _require_media_runtime(self, db, actor: GroupActor, space_id: str, runtime_kind: str, runtime_id: str):
        if runtime_kind == "radio":
            burst = db.get(GroupRadioBurst, runtime_id)
            if not burst or burst.space_id != space_id or burst.state not in {"finalizing", "final"}:
                raise GroupServiceError("group_translation_runtime_not_active", 409)
            radio_session = db.get(GroupRadioSession, burst.radio_session_id)
            if not radio_session or radio_session.status != "ready":
                raise GroupServiceError("group_translation_runtime_not_active", 409)
            participant = db.scalar(
                select(GroupRadioParticipant).where(
                    GroupRadioParticipant.radio_session_id == radio_session.id,
                    GroupRadioParticipant.principal_type == actor.principal_type,
                    GroupRadioParticipant.principal_id == actor.principal_id,
                    GroupRadioParticipant.principal_user_id == actor.principal_user_id,
                    GroupRadioParticipant.status == "joined",
                )
            )
            if not participant or participant.membership_id != burst.speaker_membership_id:
                raise GroupServiceError("group_translation_radio_speaker_required", 403)
            joined_membership_ids = list(db.scalars(select(GroupRadioParticipant.membership_id).where(GroupRadioParticipant.radio_session_id == radio_session.id, GroupRadioParticipant.status == "joined")).all())
            consented = set(db.scalars(select(GroupTranslationConsent.membership_id).where(GroupTranslationConsent.space_id == space_id, GroupTranslationConsent.membership_id.in_(joined_membership_ids), GroupTranslationConsent.status == "granted", GroupTranslationConsent.policy_version == self.settings.group_translation_policy_version)).all())
            if len(consented) != len(set(joined_membership_ids)):
                raise GroupServiceError("group_translation_all_participant_consent_required", 409)
            return burst, participant
        if runtime_kind not in {"call", "video"}:
            raise GroupServiceError("group_translation_runtime_not_ready", 409)
        session = db.get(GroupMediaSession, runtime_id)
        expected_kind = "video" if runtime_kind == "video" else "audio"
        if not session or session.space_id != space_id or session.media_kind != expected_kind or session.status != "active":
            raise GroupServiceError("group_translation_runtime_not_active", 409)
        participant = db.scalar(
            select(GroupMediaParticipant).where(
                GroupMediaParticipant.session_id == session.id,
                GroupMediaParticipant.principal_type == actor.principal_type,
                GroupMediaParticipant.principal_id == actor.principal_id,
                GroupMediaParticipant.principal_user_id == actor.principal_user_id,
                GroupMediaParticipant.invite_status == "joined",
            )
        )
        if not participant:
            raise GroupServiceError("group_translation_participant_required", 403)
        joined_membership_ids = list(db.scalars(select(GroupMediaParticipant.membership_id).where(GroupMediaParticipant.session_id == session.id, GroupMediaParticipant.invite_status == "joined")).all())
        consented = set(db.scalars(select(GroupTranslationConsent.membership_id).where(GroupTranslationConsent.space_id == space_id, GroupTranslationConsent.membership_id.in_(joined_membership_ids), GroupTranslationConsent.status == "granted", GroupTranslationConsent.policy_version == self.settings.group_translation_policy_version)).all())
        if len(consented) != len(set(joined_membership_ids)):
            raise GroupServiceError("group_translation_all_participant_consent_required", 409)
        return session, participant

    def _release_expired(self, db) -> None:
        now = _now()
        expired = list(db.scalars(select(GroupTranslationReservation).where(GroupTranslationReservation.status == "reserved", GroupTranslationReservation.expires_at <= now).with_for_update()).all())
        for reservation in expired:
            ledger = db.get(GroupTranslationQuotaLedger, reservation.quota_ledger_id)
            if ledger:
                ledger.reserved_target_seconds = max(0, ledger.reserved_target_seconds - reservation.reserved_target_seconds)
                ledger.updated_at = now
            reservation.status = "expired"
            reservation.settled_at = now
            if reservation.runtime_kind == "radio":
                burst = db.get(GroupRadioBurst, reservation.runtime_id)
                if burst and burst.state == "finalizing":
                    burst.state = "final"
                    burst.stop_reason = "translation_expired"
                    burst.finalized_at = now
                    burst.updated_at = now
                processing = db.scalar(
                    select(GroupRadioProcessingJob).where(
                        GroupRadioProcessingJob.burst_id == reservation.runtime_id
                    )
                )
                if processing and processing.status in {"ready", "processing"}:
                    processing.status = "failed"
                    processing.failure_code = "translation_reservation_expired"
                    processing.updated_at = now

    def reconcile_expired(self) -> None:
        if not self.settings.group_translation_enabled:
            return
        with self.database.session() as db:
            with db.begin():
                self._release_expired(db)

    def reserve(
        self,
        actor: GroupActor,
        space_id: str,
        values: dict,
        idempotency_key: str | None,
    ) -> dict:
        if not self.settings.group_translation_enabled:
            raise GroupServiceError("group_translation_disabled", 503)
        key = str(idempotency_key or "").strip()
        if not 8 <= len(key) <= 128 or any(character.isspace() for character in key):
            raise GroupServiceError("idempotency_key_required", 400)
        if values["source_language"] == values["target_language"]:
            raise GroupServiceError("group_translation_source_target_same", 400)
        seconds = min(values["estimated_target_seconds"], self.settings.group_translation_max_segment_seconds)
        with self.database.session() as db:
            try:
                with db.begin():
                    membership = self._membership(db, space_id, actor)
                    runtime, _runtime_participant = self._require_media_runtime(db, actor, space_id, values["runtime_kind"], values["runtime_id"])
                    if values["runtime_kind"] == "radio":
                        try:
                            radio_targets = set(json.loads(runtime.target_languages_json))
                        except json.JSONDecodeError:
                            radio_targets = set()
                        if values["target_language"] not in radio_targets or values["segment_id"] != runtime.id:
                            raise GroupServiceError("group_radio_translation_target_not_planned", 409)
                    self._release_expired(db)
                    existing = db.scalar(select(GroupTranslationReservation).where(GroupTranslationReservation.space_id == space_id, GroupTranslationReservation.runtime_kind == values["runtime_kind"], GroupTranslationReservation.runtime_id == values["runtime_id"], GroupTranslationReservation.segment_id == values["segment_id"], GroupTranslationReservation.target_language == values["target_language"]).with_for_update())
                    if existing and existing.status in {"reserved", "settled"}:
                        raise GroupServiceError("group_translation_target_already_active", 409)
                    ledger = self._sync_ledger(db, actor, values["runtime_kind"])
                    unavailable = ledger.authority_consumed_target_seconds + ledger.consumed_target_seconds + ledger.reserved_target_seconds
                    if seconds <= 0 or unavailable + seconds > ledger.limit_target_seconds:
                        raise GroupServiceError("group_translation_quota_exceeded", 429)
                    expires_at = _now() + timedelta(seconds=self.settings.group_translation_reservation_ttl_seconds)
                    if existing:
                        if existing.actor_key != actor.key:
                            raise GroupServiceError("group_translation_target_owned_by_other_actor", 409)
                        existing.quota_ledger_id = ledger.id
                        existing.payer_membership_id = membership.id
                        existing.actor_key = actor.key
                        existing.idempotency_key = key
                        existing.source_language = values["source_language"]
                        existing.reserved_target_seconds = seconds
                        existing.settled_target_seconds = 0
                        existing.status = "reserved"
                        existing.provider_session_id = ""
                        existing.provider_secret_expires_at = None
                        existing.expires_at = expires_at
                        existing.settled_at = None
                        reservation = existing
                    else:
                        reservation = GroupTranslationReservation(
                            id=str(uuid4()),
                            space_id=space_id,
                            quota_ledger_id=ledger.id,
                            payer_membership_id=membership.id,
                            actor_key=actor.key,
                            idempotency_key=key,
                            runtime_kind=values["runtime_kind"],
                            runtime_id=values["runtime_id"],
                            segment_id=values["segment_id"],
                            source_language=values["source_language"],
                            target_language=values["target_language"],
                            reserved_target_seconds=seconds,
                            expires_at=expires_at,
                        )
                        db.add(reservation)
                    ledger.reserved_target_seconds += seconds
                    ledger.updated_at = _now()
                    if values["runtime_kind"] == "radio":
                        processing = db.scalar(select(GroupRadioProcessingJob).where(GroupRadioProcessingJob.burst_id == runtime.id).with_for_update())
                        if not processing or processing.status not in {"ready", "processing", "failed", "completed"}:
                            raise GroupServiceError("group_radio_processing_not_ready", 409)
                        processing.status = "processing"
                        processing.failure_code = ""
                        processing.updated_at = _now()
                        runtime.state = "finalizing"
                        runtime.finalized_at = None
                        runtime.updated_at = _now()
                    self._audit(db, actor, space_id, "translation.reserved", "translation_reservation", reservation.id, {"runtime_kind": reservation.runtime_kind, "target_language": reservation.target_language, "target_seconds": seconds})
                    db.flush()
                    return {
                        "reservation_id": reservation.id,
                        "source_language": reservation.source_language,
                        "target_language": reservation.target_language,
                        "expires_at": _iso(reservation.expires_at),
                        "quota": self._quota_payload(ledger),
                    }
            except IntegrityError as exc:
                raise GroupServiceError("group_translation_reservation_conflict", 409) from exc

    def mark_provider_secret(self, actor: GroupActor, reservation_id: str, provider_session_id: str, expires_at: int | None) -> None:
        with self.database.session() as db:
            with db.begin():
                reservation = db.scalar(select(GroupTranslationReservation).where(GroupTranslationReservation.id == reservation_id).with_for_update())
                if not reservation or reservation.actor_key != actor.key or reservation.status != "reserved":
                    raise GroupServiceError("group_translation_reservation_not_active", 409)
                reservation.provider_session_id = provider_session_id
                reservation.provider_secret_expires_at = datetime.fromtimestamp(expires_at, timezone.utc) if expires_at else None

    def release(self, actor: GroupActor, space_id: str, reservation_id: str, *, reason: str = "released") -> dict:
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                reservation = db.scalar(select(GroupTranslationReservation).where(GroupTranslationReservation.id == reservation_id, GroupTranslationReservation.space_id == space_id).with_for_update())
                if not reservation or reservation.actor_key != actor.key:
                    raise GroupServiceError("group_translation_reservation_not_found", 404)
                ledger = db.get(GroupTranslationQuotaLedger, reservation.quota_ledger_id)
                if reservation.status == "reserved":
                    ledger.reserved_target_seconds = max(0, ledger.reserved_target_seconds - reservation.reserved_target_seconds)
                    ledger.updated_at = _now()
                    reservation.status = "released"
                    reservation.settled_at = _now()
                    if reservation.runtime_kind == "radio":
                        burst = db.get(GroupRadioBurst, reservation.runtime_id)
                        if burst and burst.state == "finalizing":
                            burst.state = "final"
                            burst.stop_reason = reason[:40]
                            burst.finalized_at = _now()
                            burst.updated_at = _now()
                        processing = db.scalar(
                            select(GroupRadioProcessingJob).where(
                                GroupRadioProcessingJob.burst_id == reservation.runtime_id
                            )
                        )
                        if processing and processing.status in {"ready", "processing"}:
                            processing.status = "failed"
                            processing.failure_code = reason[:80]
                            processing.updated_at = _now()
                    self._audit(db, actor, space_id, "translation.released", "translation_reservation", reservation.id, {"reason": reason[:80]})
                return {"reservation_id": reservation.id, "status": reservation.status, "quota": self._quota_payload(ledger)}

    def finalize(self, actor: GroupActor, space_id: str, values: dict) -> dict:
        event_id = str(uuid4())
        with self.database.session() as db:
            try:
                with db.begin():
                    self._membership(db, space_id, actor)
                    reservation = db.scalar(select(GroupTranslationReservation).where(GroupTranslationReservation.id == values["reservation_id"], GroupTranslationReservation.space_id == space_id).with_for_update())
                    if not reservation or reservation.actor_key != actor.key:
                        raise GroupServiceError("group_translation_reservation_not_found", 404)
                    existing = db.scalar(select(GroupTranslationEvent).where(GroupTranslationEvent.reservation_id == reservation.id))
                    if existing:
                        return {"event": self._event_payload(existing), "tts_jobs_created": 0, "idempotent": True}
                    if reservation.status != "reserved" or reservation.expires_at <= _now():
                        raise GroupServiceError("group_translation_reservation_not_active", 409)
                    if values["actual_target_seconds"] > reservation.reserved_target_seconds:
                        raise GroupServiceError("group_translation_actual_exceeds_reservation", 409)
                    runtime, _participant = self._require_media_runtime(db, actor, space_id, reservation.runtime_kind, reservation.runtime_id)
                    if reservation.runtime_kind == "radio":
                        speaker = db.scalar(select(GroupRadioParticipant).where(GroupRadioParticipant.radio_session_id == runtime.radio_session_id, GroupRadioParticipant.membership_id == values["speaker_membership_id"], GroupRadioParticipant.status == "joined"))
                    else:
                        speaker = db.scalar(select(GroupMediaParticipant).where(GroupMediaParticipant.session_id == runtime.id, GroupMediaParticipant.membership_id == values["speaker_membership_id"], GroupMediaParticipant.invite_status == "joined"))
                    if not speaker:
                        raise GroupServiceError("group_translation_speaker_not_joined", 409)
                    original_ciphertext, original_nonce, version = self.crypto.encrypt_text(values["original_text"], aad=f"group-translation-original:{space_id}:{event_id}")
                    translated_ciphertext, translated_nonce, translated_version = self.crypto.encrypt_text(values["translated_text"], aad=f"group-translation-translated:{space_id}:{event_id}")
                    if translated_version != version:
                        raise GroupServiceError("group_translation_encryption_version_mismatch", 500)
                    now = _now()
                    event = GroupTranslationEvent(
                        id=event_id,
                        reservation_id=reservation.id,
                        space_id=space_id,
                        speaker_membership_id=values["speaker_membership_id"],
                        runtime_kind=reservation.runtime_kind,
                        runtime_id=reservation.runtime_id,
                        segment_id=reservation.segment_id,
                        source_language=reservation.source_language,
                        target_language=reservation.target_language,
                        state="FINAL",
                        original_ciphertext=original_ciphertext,
                        original_nonce=original_nonce,
                        translated_ciphertext=translated_ciphertext,
                        translated_nonce=translated_nonce,
                        encryption_version=version,
                        duration_target_seconds=values["actual_target_seconds"],
                        confidence_millis=round(values["confidence"] * 1000) if values.get("confidence") is not None else None,
                        final_at=now,
                    )
                    db.add(event)
                    ledger = db.get(GroupTranslationQuotaLedger, reservation.quota_ledger_id)
                    ledger.reserved_target_seconds = max(0, ledger.reserved_target_seconds - reservation.reserved_target_seconds)
                    ledger.consumed_target_seconds += values["actual_target_seconds"]
                    ledger.updated_at = now
                    reservation.status = "settled"
                    reservation.settled_target_seconds = values["actual_target_seconds"]
                    reservation.settled_at = now
                    if reservation.runtime_kind == "radio":
                        runtime.state = "final"
                        runtime.finalized_at = now
                        runtime.updated_at = now
                        processing = db.scalar(select(GroupRadioProcessingJob).where(GroupRadioProcessingJob.burst_id == runtime.id).with_for_update())
                        if processing:
                            processing.status = "completed"
                            processing.updated_at = now
                    recipients = list(
                        db.execute(
                            select(GroupMembership, GroupLanguageProfile)
                            .join(GroupLanguageProfile, GroupLanguageProfile.membership_id == GroupMembership.id)
                            .join(GroupTranslationConsent, GroupTranslationConsent.membership_id == GroupMembership.id)
                            .where(
                                GroupMembership.space_id == space_id,
                                GroupMembership.status == "active",
                                GroupLanguageProfile.space_id == space_id,
                                GroupLanguageProfile.preferred_output_language == reservation.target_language,
                                GroupLanguageProfile.auto_read_enabled == 1,
                                GroupTranslationConsent.space_id == space_id,
                                GroupTranslationConsent.status == "granted",
                                GroupTranslationConsent.policy_version == self.settings.group_translation_policy_version,
                            )
                        ).all()
                    )
                    for membership, _profile in recipients:
                        db.add(GroupTtsJob(id=str(uuid4()), translation_event_id=event.id, recipient_membership_id=membership.id, language=reservation.target_language, auto_read_snapshot=1, status="pending"))
                    self._audit(db, actor, space_id, "translation.final_persisted", "translation_event", event.id, {"state": "FINAL", "target_language": event.target_language, "tts_jobs_created": len(recipients)})
                    db.flush()
                    return {"event": self._event_payload(event, values["original_text"], values["translated_text"]), "tts_jobs_created": len(recipients), "idempotent": False, "quota": self._quota_payload(ledger)}
            except IntegrityError as exc:
                raise GroupServiceError("group_translation_final_conflict", 409) from exc

    def _event_payload(self, event: GroupTranslationEvent, original: str | None = None, translated: str | None = None) -> dict:
        if original is None:
            original = self.crypto.decrypt_text(event.original_ciphertext, event.original_nonce, aad=f"group-translation-original:{event.space_id}:{event.id}", version=event.encryption_version)
        if translated is None:
            translated = self.crypto.decrypt_text(event.translated_ciphertext, event.translated_nonce, aad=f"group-translation-translated:{event.space_id}:{event.id}", version=event.encryption_version)
        return {
            "id": event.id,
            "runtime_kind": event.runtime_kind,
            "runtime_id": event.runtime_id,
            "segment_id": event.segment_id,
            "speaker_membership_id": event.speaker_membership_id,
            "source_language": event.source_language,
            "target_language": event.target_language,
            "state": "FINAL",
            "original_text": original,
            "translated_text": translated,
            "duration_target_seconds": event.duration_target_seconds,
            "confidence": round(event.confidence_millis / 1000, 3) if event.confidence_millis is not None else None,
            "final_at": _iso(event.final_at),
        }

    def history(self, actor: GroupActor, space_id: str, runtime_kind: str | None, runtime_id: str | None, limit: int) -> list[dict]:
        with self.database.session() as db:
            self._membership(db, space_id, actor)
            query = select(GroupTranslationEvent).where(GroupTranslationEvent.space_id == space_id, GroupTranslationEvent.state == "FINAL")
            if runtime_kind:
                query = query.where(GroupTranslationEvent.runtime_kind == runtime_kind)
            if runtime_id:
                query = query.where(GroupTranslationEvent.runtime_id == runtime_id)
            events = list(db.scalars(query.order_by(GroupTranslationEvent.final_at.desc()).limit(limit)).all())
            return [self._event_payload(item) for item in events]

    # ------------------------------------------------------------------
    # Translation V2: canonical source segments and recipient projections.
    # These methods deliberately do not touch LiveKit media or the legacy
    # realtime sidecar/reservation tables above.

    def _require_v2_runtime(self, db, actor: GroupActor, space_id: str, runtime_kind: str, runtime_id: str):
        membership = self._membership(db, space_id, actor)
        if runtime_kind in {"call", "video"}:
            session = db.get(GroupMediaSession, runtime_id)
            expected = "video" if runtime_kind == "video" else "audio"
            if not session or session.space_id != space_id or session.media_kind != expected or session.status != "active":
                raise GroupServiceError("group_translation_runtime_not_active", 409)
            participant = db.scalar(select(GroupMediaParticipant).where(
                GroupMediaParticipant.session_id == session.id,
                GroupMediaParticipant.membership_id == membership.id,
                GroupMediaParticipant.invite_status == "joined",
            ))
            if not participant:
                raise GroupServiceError("group_translation_participant_required", 403)
            joined_ids = list(db.scalars(select(GroupMediaParticipant.membership_id).where(
                GroupMediaParticipant.session_id == session.id,
                GroupMediaParticipant.invite_status == "joined",
            )).all())
            return membership, joined_ids
        if runtime_kind == "radio":
            session = db.get(GroupRadioSession, runtime_id)
            if not session or session.space_id != space_id or session.status != "ready":
                raise GroupServiceError("group_translation_runtime_not_active", 409)
            participant = db.scalar(select(GroupRadioParticipant).where(
                GroupRadioParticipant.radio_session_id == session.id,
                GroupRadioParticipant.membership_id == membership.id,
                GroupRadioParticipant.status == "joined",
            ))
            if not participant:
                raise GroupServiceError("group_translation_participant_required", 403)
            joined_ids = list(db.scalars(select(GroupRadioParticipant.membership_id).where(
                GroupRadioParticipant.radio_session_id == session.id,
                GroupRadioParticipant.status == "joined",
            )).all())
            return membership, joined_ids
        raise GroupServiceError("group_translation_runtime_not_ready", 409)

    def _voice_consent_required(self, db, space_id: str, membership_id: str) -> None:
        consent = db.scalar(select(GroupTranslationConsent).where(
            GroupTranslationConsent.space_id == space_id,
            GroupTranslationConsent.membership_id == membership_id,
        ))
        if not consent or consent.status != "granted" or consent.policy_version != self.settings.group_translation_policy_version:
            raise GroupServiceError("group_translation_voice_consent_required", 409)

    def _authorize_v2_history(self, db, actor, space_id, runtime_kind, runtime_id):
        """Archive reads preserve membership/participation, not active transport state."""
        member = self._membership(db, space_id, actor)
        if runtime_kind in {"call", "video"}:
            session = db.get(GroupMediaSession, runtime_id)
            expected = "video" if runtime_kind == "video" else "audio"
            if not session or session.space_id != space_id or session.media_kind != expected:
                raise GroupServiceError("group_translation_runtime_not_found", 404)
            participant = db.scalar(select(GroupMediaParticipant).where(
                GroupMediaParticipant.session_id == runtime_id,
                GroupMediaParticipant.membership_id == member.id,
                GroupMediaParticipant.joined_at.is_not(None),
            ))
        elif runtime_kind == "radio":
            session = db.get(GroupRadioSession, runtime_id)
            if not session or session.space_id != space_id:
                raise GroupServiceError("group_translation_runtime_not_found", 404)
            participant = db.scalar(select(GroupRadioParticipant).where(
                GroupRadioParticipant.radio_session_id == runtime_id,
                GroupRadioParticipant.membership_id == member.id,
                GroupRadioParticipant.joined_at.is_not(None),
            ))
        else:
            raise GroupServiceError("group_translation_runtime_not_found", 404)
        if not participant:
            raise GroupServiceError("group_translation_participant_required", 403)
        return member

    def _submission_context(self, db, actor, space_id, values):
        # Only the authenticated Radio finalize entry point sets this private value.
        burst_id = values.get("_radio_burst_id")
        if not burst_id:
            return self._require_v2_runtime(db, actor, space_id, values["runtime_kind"], values["runtime_id"])
        member = self._authorize_v2_history(db, actor, space_id, "radio", values["runtime_id"])
        burst = db.get(GroupRadioBurst, burst_id)
        if (not burst or burst.space_id != space_id or burst.radio_session_id != values["runtime_id"]
                or burst.speaker_membership_id != member.id or burst.stopped_at is None
                or burst.state == "talking" or values["client_segment_id"] != burst.id):
            raise GroupServiceError("group_radio_burst_not_released", 409)
        joined_ids = list(db.scalars(select(GroupRadioParticipant.membership_id).where(
            GroupRadioParticipant.radio_session_id == burst.radio_session_id,
            GroupRadioParticipant.joined_at.is_not(None),
            GroupRadioParticipant.joined_at <= burst.stopped_at,
            or_(GroupRadioParticipant.left_at.is_(None), GroupRadioParticipant.left_at >= burst.started_at),
        )).all())
        return member, joined_ids

    async def _resolve_source_language(self, actor, language, source_text, client_id):
        if language in {"vi", "en", "zh-TW"}:
            return language
        if language != "auto":
            raise GroupServiceError("group_translation_language_invalid", 400)
        if self.provider is None or not hasattr(self.provider, "detect_supported_language"):
            raise GroupServiceError("group_translation_provider_not_configured", 503)
        try:
            resolved = await self.provider.detect_supported_language(
                source_text, actor.key, f"group-v2-detect:{client_id}"
            )
        except Exception as exc:
            raise GroupServiceError("group_translation_provider_unavailable", 502) from exc
        if resolved not in {"vi", "en", "zh-TW"}:
            raise GroupServiceError("group_translation_detected_language_unsupported", 422)
        return resolved

    def _target_languages(self, db, space_id: str, membership_ids: list[str], source_language: str) -> list[str]:
        if not membership_ids:
            return []
        members = list(db.scalars(select(GroupMembership).where(
            GroupMembership.space_id == space_id,
            GroupMembership.id.in_(set(membership_ids)),
            GroupMembership.status == "active",
        )).all())
        profiles = list(db.scalars(select(GroupLanguageProfile).where(
            GroupLanguageProfile.space_id == space_id,
            GroupLanguageProfile.membership_id.in_(set(membership_ids)),
        )).all())
        profile_by_member = {profile.membership_id: profile for profile in profiles}
        targets = set()
        for member in members:
            effective = self._effective_language_profile(
                db, member, source_language, profile=profile_by_member.get(member.id)
            )
            # Segment V2 is explicitly submitted. The legacy automatic switch
            # must not override the participant's chosen output language.
            targets.add(effective["preferred_output_language"])
        targets.discard(source_language)
        return sorted(targets)[: max(1, int(self.settings.group_translation_max_targets))]

    @staticmethod
    def _segment_state(variants: list[GroupTranslationVariant]) -> str:
        if not variants or all(v.state == "FINAL" for v in variants):
            return "FINAL"
        if any(v.state == "FINAL" for v in variants):
            return "PARTIAL"
        if all(v.state == "FAILED" for v in variants):
            return "FAILED"
        return "PROCESSING"

    def _project_v2(self, db, actor: GroupActor, segment: GroupTranslationSegment, target_override: str | None = None) -> dict:
        membership = self._membership(db, segment.space_id, actor)
        profile = db.scalar(select(GroupLanguageProfile).where(
            GroupLanguageProfile.space_id == segment.space_id,
            GroupLanguageProfile.membership_id == membership.id,
        ))
        effective = self._effective_language_profile(
            db, membership, segment.source_language, actor=actor, profile=profile
        )
        target = target_override or effective["preferred_output_language"] or segment.source_language
        if target not in {"vi", "en", "zh-TW"}:
            target = segment.source_language
        source = self.crypto.decrypt_text(
            segment.source_ciphertext, segment.source_nonce,
            aad=f"group-translation-segment-source:{segment.space_id}:{segment.id}",
            version=segment.encryption_version,
        )
        variant = db.scalar(select(GroupTranslationVariant).where(
            GroupTranslationVariant.segment_id == segment.id,
            GroupTranslationVariant.target_language == target,
        ))
        translated = source if target == segment.source_language else None
        if variant and variant.state == "FINAL" and variant.translated_ciphertext and variant.translated_nonce and variant.encryption_version:
            translated = self.crypto.decrypt_text(
                variant.translated_ciphertext, variant.translated_nonce,
                aad=f"group-translation-variant:{segment.id}:{variant.target_language}",
                version=variant.encryption_version,
            )
        if target == segment.source_language:
            projected_state = "FINAL"
            projected_failure = None
        elif variant:
            projected_state = variant.state
            projected_failure = variant.failure_code if variant.state == "FAILED" else None
            if variant.state == "FINAL" and translated is None:
                projected_state = "FAILED"
                projected_failure = "group_translation_variant_missing"
        elif segment.state == "FAILED":
            projected_state = "FAILED"
            projected_failure = segment.failure_code or "group_translation_variant_missing"
        elif segment.state in {"FINAL", "PARTIAL"}:
            # A recipient may change preferred language after a segment was
            # created. Never expose the contradictory FINAL + null projection.
            projected_state = "FAILED"
            projected_failure = "group_translation_variant_missing"
        else:
            projected_state = "PROCESSING"
            projected_failure = None
        payload = {
            "id": segment.id,
            "client_segment_id": segment.client_segment_id,
            "runtime_kind": segment.runtime_kind,
            "runtime_id": segment.runtime_id,
            "speaker_membership_id": segment.speaker_membership_id,
            "speaker_display_name": (db.get(GroupMembership, segment.speaker_membership_id).display_name),
            "input_kind": segment.input_kind,
            "source_language": segment.source_language,
            "target_language": target,
            "source_text": source,
            "translated_text": translated,
            "state": projected_state,
            "failure_code": projected_failure,
            "is_original": target == segment.source_language,
            "auto_read_enabled": effective["auto_read_enabled"],
            "show_original_enabled": effective["show_original_enabled"],
            "profile_source": effective["profile_source"],
            "display_language": target,
            "projection": "recipient",
            "created_at": _iso(segment.created_at),
        }
        # The speaker receives an author projection with every generated
        # language variant and a recipient count. Other participants receive
        # only their own preferred-output projection above.
        if membership.id == segment.speaker_membership_id and target_override is None:
            if segment.runtime_kind in {"call", "video"}:
                joined_ids = list(db.scalars(select(GroupMediaParticipant.membership_id).where(
                    GroupMediaParticipant.session_id == segment.runtime_id,
                    GroupMediaParticipant.invite_status == "joined",
                )).all())
            else:
                joined_ids = list(db.scalars(select(GroupRadioParticipant.membership_id).where(
                    GroupRadioParticipant.radio_session_id == segment.runtime_id,
                    GroupRadioParticipant.status == "joined",
                )).all())
            recipients = [item for item in joined_ids if item != membership.id]
            profiles = list(db.scalars(select(GroupLanguageProfile).where(
                GroupLanguageProfile.space_id == segment.space_id,
                GroupLanguageProfile.membership_id.in_(set(recipients)),
            )).all()) if recipients else []
            profile_by_member = {item.membership_id: item for item in profiles}
            members = list(db.scalars(select(GroupMembership).where(
                GroupMembership.space_id == segment.space_id,
                GroupMembership.id.in_(set(recipients)),
                GroupMembership.status == "active",
            )).all()) if recipients else []
            effective_by_member = {
                item.id: self._effective_language_profile(
                    db, item, segment.source_language, profile=profile_by_member.get(item.id)
                )
                for item in members
            }
            variants = []
            source_recipient_count = sum(
                1 for item in effective_by_member.values()
                if item["preferred_output_language"] == segment.source_language
            )
            variants.append({
                "target_language": segment.source_language,
                "state": "FINAL",
                "translated_text": source,
                "recipient_count": source_recipient_count,
            })
            for row in db.scalars(select(GroupTranslationVariant).where(GroupTranslationVariant.segment_id == segment.id).order_by(GroupTranslationVariant.target_language)).all():
                value = None
                if row.state == "FINAL" and row.translated_ciphertext and row.translated_nonce and row.encryption_version:
                    value = self.crypto.decrypt_text(
                        row.translated_ciphertext, row.translated_nonce,
                        aad=f"group-translation-variant:{segment.id}:{row.target_language}", version=row.encryption_version,
                    )
                row_state = row.state
                row_failure = row.failure_code
                if row_state == "FINAL" and value is None:
                    row_state = "FAILED"
                    row_failure = "group_translation_variant_missing"
                variants.append({
                    "target_language": row.target_language,
                    "state": row_state,
                    "translated_text": value,
                    "recipient_count": sum(
                        1 for item in effective_by_member.values()
                        if item["preferred_output_language"] == row.target_language
                    ),
                    "failure_code": row_failure,
                })
            payload["variants"] = variants
            payload["author_view"] = True
            payload["state"] = segment.state
            payload["projection"] = "author"
        else:
            payload["author_view"] = False
        return payload

    async def _translate_variant_locked(
        self,
        cost_owner_key: str,
        segment_id: str,
        source_text: str,
        source_language: str,
        target: str,
        *,
        event_type: str,
    ) -> None:
        # Caller owns the canonical (segment, target) lock.
        with self.database.session() as db:
            variant = db.scalar(select(GroupTranslationVariant).where(
                GroupTranslationVariant.segment_id == segment_id,
                GroupTranslationVariant.target_language == target,
            ))
            if not variant or (
                variant.state == "FINAL"
                and variant.translated_ciphertext
                and variant.translated_nonce
                and variant.encryption_version
            ):
                return
        try:
            if self.provider is None:
                raise GroupServiceError("group_translation_provider_not_configured", 503)
            result = await self.provider.translate_text(
                source_text=source_text,
                source_language=source_language,
                target_language=target,
                principal_id=cost_owner_key,
                idempotency_key=f"group-v2:{segment_id}:{target}",
            )
            outcome = ("FINAL", result.text, result.model, result.request_id, "")
        except Exception as exc:
            code = getattr(exc, "args", [None])[0] or "group_translation_provider_failed"
            outcome = ("FAILED", None, "", "", str(code)[:80])
        event_space_id = ""
        with self.database.session() as db:
            with db.begin():
                variant = db.scalar(select(GroupTranslationVariant).where(
                    GroupTranslationVariant.segment_id == segment_id,
                    GroupTranslationVariant.target_language == target,
                ).with_for_update())
                if not variant:
                    return
                variant.state, text_value, variant.provider_model, variant.provider_request_id, variant.failure_code = outcome
                variant.updated_at = _now()
                if text_value is not None:
                    ciphertext, nonce, version = self.crypto.encrypt_text(
                        text_value, aad=f"group-translation-variant:{segment_id}:{target}"
                    )
                    variant.translated_ciphertext = ciphertext
                    variant.translated_nonce = nonce
                    variant.encryption_version = version
                else:
                    # A failed retry must not expose stale ciphertext as a
                    # successful historical translation.
                    variant.translated_ciphertext = None
                    variant.translated_nonce = None
                    variant.encryption_version = None
                segment = db.get(GroupTranslationSegment, segment_id)
                if segment:
                    event_space_id = segment.space_id
                    variants = list(db.scalars(select(GroupTranslationVariant).where(
                        GroupTranslationVariant.segment_id == segment_id,
                    )).all())
                    segment.state = self._segment_state(variants)
                    segment.failure_code = next((
                        item.failure_code for item in variants
                        if item.state == "FAILED" and item.failure_code
                    ), "")
                    if self.event_broker:
                        self.event_broker.enqueue_in_transaction(
                            db, segment.space_id, event_type, resource_id=segment.id
                        )
        if self.event_broker and event_space_id:
            await self.event_broker.publish(
                event_space_id, event_type, resource_id=segment_id
            )

    async def _translate_variants(
        self,
        cost_owner_key: str,
        segment_id: str,
        source_text: str,
        source_language: str,
        targets: list[str],
        *,
        event_type: str = "translation.segment.changed",
    ) -> None:
        if not targets:
            with self.database.session() as db:
                with db.begin():
                    segment = db.get(GroupTranslationSegment, segment_id)
                    if segment:
                        segment.state = "FINAL"
            return
        import asyncio
        semaphore = asyncio.Semaphore(3)

        async def one(target: str) -> None:
            lock_key = f"{segment_id}:{target}"
            lock = self._variant_locks.setdefault(lock_key, asyncio.Lock())
            async with semaphore, lock:
                await self._translate_variant_locked(
                    cost_owner_key, segment_id, source_text, source_language,
                    target, event_type=event_type,
                )

        await asyncio.gather(*(one(target) for target in targets))

    async def submit_text(self, actor: GroupActor, space_id: str, values: dict, idempotency_key: str | None = None) -> dict:
        if not self.settings.group_translation_enabled:
            raise GroupServiceError("group_translation_disabled", 503)
        source_text = str(values.get("source_text") or "").strip()
        if not source_text or len(source_text) > 12000:
            raise GroupServiceError("group_translation_text_invalid", 400)
        source_language = str(values.get("source_language") or "")
        if source_language not in {"vi", "en", "zh-TW", "auto"}:
            raise GroupServiceError("group_translation_language_invalid", 400)
        runtime_kind = values["runtime_kind"]
        client_segment_id = str(values["client_segment_id"]).strip()
        if not 8 <= len(client_segment_id) <= 128 or any(character.isspace() for character in client_segment_id):
            raise GroupServiceError("group_translation_segment_id_invalid", 400)
        supplied_idempotency = str(idempotency_key or "").strip()
        if supplied_idempotency and supplied_idempotency != client_segment_id:
            raise GroupServiceError("group_translation_idempotency_mismatch", 400)
        input_kind = str(values.get("input_kind") or "text")
        if input_kind not in {"text", "voice"}:
            raise GroupServiceError("group_translation_input_invalid", 400)
        # Authorize before sending untrusted text to a provider. Detection mode
        # never enters either the profile table or canonical source column.
        with self.database.session() as db:
            member, _ = self._submission_context(db, actor, space_id, values)
            existing = db.scalar(select(GroupTranslationSegment).where(
                GroupTranslationSegment.space_id == space_id,
                GroupTranslationSegment.runtime_kind == runtime_kind,
                GroupTranslationSegment.runtime_id == values["runtime_id"],
                GroupTranslationSegment.speaker_membership_id == member.id,
                GroupTranslationSegment.client_segment_id == client_segment_id,
            ))
            if existing:
                return self._project_v2(db, actor, existing)
        source_language = await self._resolve_source_language(actor, source_language, source_text, client_segment_id)
        with self.database.session() as db:
            with db.begin():
                membership, joined_ids = self._submission_context(db, actor, space_id, values)
                existing = db.scalar(select(GroupTranslationSegment).where(
                    GroupTranslationSegment.space_id == space_id,
                    GroupTranslationSegment.runtime_kind == runtime_kind,
                    GroupTranslationSegment.runtime_id == values["runtime_id"],
                    GroupTranslationSegment.speaker_membership_id == membership.id,
                    GroupTranslationSegment.client_segment_id == client_segment_id,
                ))
                if existing:
                    return self._project_v2(db, actor, existing)
                segment_id = str(uuid4())
                ciphertext, nonce, version = self.crypto.encrypt_text(source_text, aad=f"group-translation-segment-source:{space_id}:{segment_id}")
                segment = GroupTranslationSegment(
                    id=segment_id, client_segment_id=client_segment_id, space_id=space_id,
                    runtime_kind=runtime_kind, runtime_id=values["runtime_id"], speaker_membership_id=membership.id,
                    input_kind=input_kind, source_language=source_language,
                    source_ciphertext=ciphertext, source_nonce=nonce, encryption_version=version,
                    state="PROCESSING",
                )
                db.add(segment)
                targets = self._target_languages(db, space_id, joined_ids, source_language)
                for target in targets:
                    db.add(GroupTranslationVariant(id=str(uuid4()), segment_id=segment.id, target_language=target, state="PROCESSING"))
                db.flush()
                if self.event_broker:
                    self.event_broker.enqueue_in_transaction(db, space_id, "translation.segment.created", resource_id=segment.id)
                payload = self._project_v2(db, actor, segment)
        if self.event_broker:
            await self.event_broker.publish(space_id, "translation.segment.created", resource_id=segment.id)
        await self._translate_variants(actor.key, segment.id, source_text, source_language, targets)
        with self.database.session() as db:
            segment = db.get(GroupTranslationSegment, segment.id)
            return self._project_v2(db, actor, segment) if segment else payload

    async def submit_voice(self, actor: GroupActor, space_id: str, values: dict, audio: bytes, filename: str, content_type: str) -> dict:
        lock_key = ":".join(
            (
                str(space_id),
                str(values.get("runtime_kind") or ""),
                str(values.get("runtime_id") or ""),
                str(actor.key),
                str(values.get("client_segment_id") or ""),
            )
        )
        lock = self._voice_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            return await self._submit_voice_once(actor, space_id, values, audio, filename, content_type)

    async def _submit_voice_once(self, actor: GroupActor, space_id: str, values: dict, audio: bytes, filename: str, content_type: str) -> dict:
        if values.get("source_language") not in {"vi", "en", "zh-TW", "auto"}:
            raise GroupServiceError("group_translation_language_invalid", 400)
        if not audio or len(audio) > self.settings.group_translation_max_audio_bytes or (content_type and not str(content_type).lower().startswith("audio/")):
            raise GroupServiceError("group_translation_audio_invalid", 413)
        duration = values.get("duration_seconds")
        if duration is not None:
            try:
                if float(duration) <= 0 or float(duration) > self.settings.group_translation_max_segment_seconds:
                    raise GroupServiceError("group_translation_audio_invalid", 400)
            except (TypeError, ValueError) as exc:
                raise GroupServiceError("group_translation_audio_invalid", 400) from exc
        with self.database.session() as db:
            with db.begin():
                membership, _joined_ids = self._submission_context(db, actor, space_id, values)
                self._voice_consent_required(db, space_id, membership.id)
                existing = db.scalar(select(GroupTranslationSegment).where(
                    GroupTranslationSegment.space_id == space_id,
                    GroupTranslationSegment.runtime_kind == values["runtime_kind"],
                    GroupTranslationSegment.runtime_id == values["runtime_id"],
                    GroupTranslationSegment.speaker_membership_id == membership.id,
                    GroupTranslationSegment.client_segment_id == values["client_segment_id"],
                ))
                if existing:
                    return self._project_v2(db, actor, existing)
        if self.provider is None or not hasattr(self.provider, "transcribe_audio"):
            raise GroupServiceError("group_translation_provider_not_configured", 503)
        try:
            transcription = await self.provider.transcribe_audio(
                audio=audio, filename=filename, content_type=content_type,
                source_language=values["source_language"], principal_id=actor.key,
                idempotency_key=f"group-v2-stt:{space_id}:{values['client_segment_id']}",
            )
        except GroupServiceError:
            raise
        except Exception as exc:
            raise GroupServiceError(str(getattr(exc, "args", [None])[0] or "group_translation_provider_failed"), 502) from exc
        values = dict(values)
        values["source_text"] = transcription.text
        values["input_kind"] = "voice"
        return await self.submit_text(actor, space_id, values)

    async def submit_radio_voice(self, actor, space_id, session_id, burst_id, fields, audio, filename, content_type):
        """A durable single attempt per released burst; no audio is retained for retry."""
        values = {"runtime_kind": "radio", "runtime_id": session_id, "client_segment_id": burst_id,
                  "_radio_burst_id": burst_id, "duration_seconds": fields.get("duration_seconds")}
        with self.database.session() as db:
            with db.begin():
                member, _ = self._submission_context(db, actor, space_id, values)
                self._voice_consent_required(db, space_id, member.id)
                burst = db.get(GroupRadioBurst, burst_id)
                values["source_language"] = fields.get("source_language") or burst.source_language
                if values["source_language"] not in {"vi", "en", "zh-TW", "auto"}:
                    raise GroupServiceError("group_translation_language_invalid", 400)
                existing = db.scalar(select(GroupTranslationSegment).where(
                    GroupTranslationSegment.space_id == space_id,
                    GroupTranslationSegment.runtime_kind == "radio",
                    GroupTranslationSegment.runtime_id == session_id,
                    GroupTranslationSegment.speaker_membership_id == member.id,
                    GroupTranslationSegment.client_segment_id == burst_id,
                ))
                if existing:
                    return self._project_v2(db, actor, existing)
                # Compare-and-set is effective across workers and repeat requests.
                claimed = db.execute(update(GroupRadioProcessingJob).where(
                    GroupRadioProcessingJob.burst_id == burst_id,
                    GroupRadioProcessingJob.status == "ready",
                ).values(status="processing", updated_at=_now())).rowcount
                if not claimed:
                    raise GroupServiceError("group_radio_transcription_already_submitted", 409)
        try:
            result = await self._submit_voice_once(actor, space_id, values, audio, filename, content_type)
        except Exception:
            with self.database.session() as db:
                with db.begin():
                    db.execute(update(GroupRadioProcessingJob).where(
                        GroupRadioProcessingJob.burst_id == burst_id,
                        GroupRadioProcessingJob.status == "processing",
                    ).values(status="failed", failure_code="group_radio_transcription_failed", updated_at=_now()))
                    burst = db.get(GroupRadioBurst, burst_id)
                    if burst:
                        burst.state, burst.finalized_at = "failed", _now()
                        if self.event_broker:
                            self.event_broker.enqueue_in_transaction(db, space_id, "radio.message_changed", resource_id=burst_id)
            if self.event_broker:
                await self.event_broker.publish(space_id, "radio.message_changed", resource_id=burst_id)
            raise
        with self.database.session() as db:
            with db.begin():
                burst = db.get(GroupRadioBurst, burst_id)
                if burst:
                    burst.state = "final" if result["state"] == "FINAL" else "failed"
                    burst.source_language = result["source_language"]
                    burst.finalized_at = _now()
                    db.execute(update(GroupRadioProcessingJob).where(GroupRadioProcessingJob.burst_id == burst_id)
                        .values(status="completed", updated_at=_now()))
                    if self.event_broker:
                        self.event_broker.enqueue_in_transaction(db, space_id, "radio.message_changed", resource_id=burst_id)
        if self.event_broker:
            await self.event_broker.publish(space_id, "radio.message_changed", resource_id=burst_id)
        return result

    def discard_radio_clip(self, actor, space_id, session_id, burst_id):
        values = {"runtime_kind": "radio", "runtime_id": session_id, "client_segment_id": burst_id,
                  "_radio_burst_id": burst_id}
        with self.database.session() as db:
            with db.begin():
                self._submission_context(db, actor, space_id, values)
                changed = db.execute(update(GroupRadioProcessingJob).where(
                    GroupRadioProcessingJob.burst_id == burst_id, GroupRadioProcessingJob.status == "ready",
                ).values(status="failed", failure_code="group_translation_audio_invalid", updated_at=_now())).rowcount
                if changed:
                    burst = db.get(GroupRadioBurst, burst_id)
                    burst.state, burst.finalized_at = "failed", _now()
                    if self.event_broker:
                        self.event_broker.enqueue_in_transaction(db, space_id, "radio.message_changed", resource_id=burst_id)

    def v2_history(self, actor: GroupActor, space_id: str, runtime_kind: str | None, runtime_id: str | None, limit: int, before_id: str | None = None) -> list[dict]:
        with self.database.session() as db:
            self._membership(db, space_id, actor)
            if runtime_kind and runtime_id:
                self._authorize_v2_history(db, actor, space_id, runtime_kind, runtime_id)
            elif runtime_id:
                raise GroupServiceError("invalid_runtime_kind", 400)
            query = select(GroupTranslationSegment).where(GroupTranslationSegment.space_id == space_id)
            if runtime_kind:
                query = query.where(GroupTranslationSegment.runtime_kind == runtime_kind)
            if runtime_id:
                query = query.where(GroupTranslationSegment.runtime_id == runtime_id)
            # Space archive is source history for every current authorized
            # member, including members who joined after an older runtime.
            # Missing target variants remain explicit/on-demand below; merely
            # reading this query never starts provider work.
            if before_id:
                cursor = db.get(GroupTranslationSegment, before_id)
                if not cursor or cursor.space_id != space_id:
                    raise GroupServiceError("invalid_history_cursor", 400)
                # Compare database values without rebinding a SQL timestamp as a
                # microsecond-formatted Python datetime (SQLite legacy rows).
                cursor_time = select(GroupTranslationSegment.created_at).where(
                    GroupTranslationSegment.id == cursor.id).scalar_subquery()
                query = query.where(or_(GroupTranslationSegment.created_at < cursor_time,
                    and_(GroupTranslationSegment.created_at == cursor_time, GroupTranslationSegment.id < cursor.id)))
            rows = list(
                db.scalars(
                    query.order_by(GroupTranslationSegment.created_at.desc(), GroupTranslationSegment.id.desc()).limit(
                        max(1, min(limit, 100))
                    )
                ).all()
            )
            return [self._project_v2(db, actor, row) for row in rows]

    async def retry_variant(self, actor: GroupActor, space_id: str, segment_id: str, target_language: str) -> dict:
        if target_language not in {"vi", "en", "zh-TW"}:
            raise GroupServiceError("invalid_language", 400)
        lock_key = f"{segment_id}:{target_language}"
        lock = self._variant_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            with self.database.session() as db:
                with db.begin():
                    segment = db.get(GroupTranslationSegment, segment_id)
                    if not segment or segment.space_id != space_id:
                        raise GroupServiceError("group_translation_segment_not_found", 404)
                    # Historical translation is available to current Group
                    # members and must not depend on an active media runtime.
                    self._membership(db, space_id, actor)
                    if target_language == segment.source_language:
                        return self._project_v2(db, actor, segment, target_override=target_language)
                    variant = db.scalar(select(GroupTranslationVariant).where(
                        GroupTranslationVariant.segment_id == segment.id,
                        GroupTranslationVariant.target_language == target_language,
                    ))
                    if (
                        variant
                        and variant.state == "FINAL"
                        and variant.translated_ciphertext
                        and variant.translated_nonce
                        and variant.encryption_version
                    ):
                        return self._project_v2(db, actor, segment, target_override=target_language)
                    if not variant:
                        variant = GroupTranslationVariant(
                            id=str(uuid4()), segment_id=segment.id,
                            target_language=target_language, state="PROCESSING",
                        )
                        db.add(variant)
                    else:
                        variant.state = "PROCESSING"
                        variant.failure_code = ""
                        variant.updated_at = _now()
                    source_author = db.get(GroupMembership, segment.speaker_membership_id)
                    if not source_author:
                        raise GroupServiceError("group_translation_cost_owner_unavailable", 409)
                    cost_owner_key = self._membership_actor_key(source_author)
                    source_text = self.crypto.decrypt_text(
                        segment.source_ciphertext, segment.source_nonce,
                        aad=f"group-translation-segment-source:{space_id}:{segment.id}",
                        version=segment.encryption_version,
                    )
                    source_language = segment.source_language

            # retry_variant already owns this canonical lock.  Perform the one
            # provider call inline, then persist through the common worker.
            # Temporarily release/reacquire is unnecessary because the worker
            # supports a caller-held lock via the focused helper below.
            await self._translate_variant_locked(
                cost_owner_key, segment.id, source_text, source_language,
                target_language, event_type="translation.segment.history_changed",
            )
        with self.database.session() as db:
            return self._project_v2(db, actor, db.get(GroupTranslationSegment, segment.id), target_override=target_language)

    def claim_tts_job(self, actor: GroupActor, space_id: str) -> dict | None:
        with self.database.session() as db:
            with db.begin():
                membership = self._membership(db, space_id, actor)
                job = db.scalar(select(GroupTtsJob).join(GroupTranslationEvent, GroupTranslationEvent.id == GroupTtsJob.translation_event_id).where(GroupTtsJob.recipient_membership_id == membership.id, GroupTtsJob.status == "pending", GroupTranslationEvent.space_id == space_id).order_by(GroupTtsJob.created_at).with_for_update(skip_locked=True))
                if not job:
                    return None
                event = db.get(GroupTranslationEvent, job.translation_event_id)
                job.status = "claimed"
                job.claimed_at = _now()
                translated = self.crypto.decrypt_text(event.translated_ciphertext, event.translated_nonce, aad=f"group-translation-translated:{event.space_id}:{event.id}", version=event.encryption_version)
                return {
                    "id": job.id,
                    "translation_event_id": event.id,
                    "language": job.language,
                    "text": translated,
                    "status": job.status,
                    "final_visible_event_id": event.id,
                }

    def ack_tts_job(self, actor: GroupActor, space_id: str, job_id: str, status: str, failure_code: str) -> dict:
        with self.database.session() as db:
            with db.begin():
                membership = self._membership(db, space_id, actor)
                job = db.scalar(select(GroupTtsJob).join(GroupTranslationEvent, GroupTranslationEvent.id == GroupTtsJob.translation_event_id).where(GroupTtsJob.id == job_id, GroupTtsJob.recipient_membership_id == membership.id, GroupTranslationEvent.space_id == space_id).with_for_update())
                if not job:
                    raise GroupServiceError("group_tts_job_not_found", 404)
                if job.status not in {"claimed", status}:
                    raise GroupServiceError("group_tts_job_not_claimed", 409)
                job.status = status
                job.failure_code = failure_code if status == "failed" else ""
                job.completed_at = _now()
                return {"id": job.id, "status": job.status, "completed_at": _iso(job.completed_at)}
