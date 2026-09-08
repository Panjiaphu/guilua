from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db import Database
from app.group_translation.provider import (
    GroupTranslationProviderError,
    OpenAIGroupTranslationProvider,
)
from app.group_v3.auth import GroupActor
from app.group_v3.crypto import GroupCrypto
from app.group_v3.service import GroupServiceError
from app.models import (
    GroupAuditEvent,
    GroupChatTranslation,
    GroupChatTranslationCostLedger,
    GroupChatTranslationRequest,
    GroupLanguageProfile,
    GroupMembership,
    GroupMessage,
    GroupTranslationConsent,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


class GroupChatTranslationService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        crypto: GroupCrypto,
        provider: OpenAIGroupTranslationProvider,
    ) -> None:
        self.database = database
        self.settings = settings
        self.crypto = crypto
        self.provider = provider

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
    def _audit(
        db,
        actor: GroupActor,
        space_id: str,
        event_type: str,
        translation_id: str,
        *,
        outcome: str = "success",
        metadata: dict | None = None,
    ) -> None:
        db.add(
            GroupAuditEvent(
                id=str(uuid4()),
                space_id=space_id,
                actor_type=actor.principal_type,
                actor_id=actor.principal_id,
                actor_user_id=actor.principal_user_id,
                event_type=event_type,
                resource_type="chat_translation",
                resource_id=translation_id,
                outcome=outcome,
                metadata_json=json.dumps(
                    metadata or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            )
        )

    def _message_text(self, message: GroupMessage) -> str:
        return self.crypto.decrypt_text(
            message.content_ciphertext,
            message.content_nonce,
            aad=f"group-message:{message.space_id}:{message.id}",
            version=message.encryption_version,
        )

    @staticmethod
    def _fingerprint(message: GroupMessage, text: str) -> str:
        revision = _iso(message.edited_at) or _iso(message.created_at) or ""
        return hashlib.sha256(
            f"{message.id}\0{revision}\0{text}".encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _provider_idempotency_key(
        message_id: str,
        message_fingerprint: str,
        target_language: str,
    ) -> str:
        identity = f"{message_id}\0{message_fingerprint}\0{target_language}"
        return f"group-chat-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"

    def _sync_cost_ledger(self, db, actor: GroupActor) -> GroupChatTranslationCostLedger:
        now = _now()
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_end = (
            period_start.replace(year=period_start.year + 1, month=1)
            if period_start.month == 12
            else period_start.replace(month=period_start.month + 1)
        )
        ledger_query = (
            select(GroupChatTranslationCostLedger)
            .where(
                GroupChatTranslationCostLedger.billing_subject == actor.key[:160],
                GroupChatTranslationCostLedger.period_start == period_start,
            )
            .with_for_update()
        )
        ledger = db.scalar(ledger_query)
        if not ledger:
            candidate = GroupChatTranslationCostLedger(
                id=str(uuid4()),
                billing_subject=actor.key[:160],
                period_start=period_start,
                period_end=period_end,
                limit_variant_units=self.settings.group_chat_translation_monthly_variant_limit,
            )
            try:
                with db.begin_nested():
                    db.add(candidate)
                    db.flush()
                ledger = candidate
            except IntegrityError:
                ledger = db.scalar(ledger_query)
                if not ledger:
                    raise
        else:
            ledger.period_end = period_end
            ledger.limit_variant_units = self.settings.group_chat_translation_monthly_variant_limit
            ledger.updated_at = now
        self._release_expired_ledger_reservations(db, ledger, now)
        return ledger

    @staticmethod
    def _release_expired_ledger_reservations(
        db,
        ledger: GroupChatTranslationCostLedger,
        now: datetime,
    ) -> None:
        """Recover quota held by a cancelled worker or crashed process."""

        stale = list(
            db.execute(
                select(GroupChatTranslationRequest, GroupChatTranslation)
                .join(
                    GroupChatTranslation,
                    GroupChatTranslation.id == GroupChatTranslationRequest.translation_id,
                )
                .where(
                    GroupChatTranslationRequest.cost_ledger_id == ledger.id,
                    GroupChatTranslationRequest.cost_state == "reserved",
                    or_(
                        GroupChatTranslation.status == "failed",
                        (
                            (GroupChatTranslation.status == "pending")
                            & GroupChatTranslation.lease_expires_at.is_not(None)
                            & (GroupChatTranslation.lease_expires_at <= now)
                        ),
                    ),
                )
                .with_for_update()
            ).all()
        )
        for request_row, item in stale:
            units = max(0, int(request_row.reserved_variant_units or 0))
            ledger.reserved_variant_units = max(
                0, int(ledger.reserved_variant_units or 0) - units
            )
            request_row.cost_state = "released"
            request_row.reserved_variant_units = 0
            request_row.updated_at = now
            if (
                item.status == "pending"
                and item.claim_token == request_row.claim_token
            ):
                item.status = "failed"
                item.cost_state = "released"
                item.claim_token = ""
                item.lease_expires_at = None
                item.failure_code = "group_translation_reservation_expired"
                item.updated_at = now
        if stale:
            ledger.updated_at = now

    @staticmethod
    def _release_reserved_cost(db, item: GroupChatTranslation, now: datetime) -> None:
        owner_request = db.scalar(
            select(GroupChatTranslationRequest)
            .where(
                GroupChatTranslationRequest.translation_id == item.id,
                GroupChatTranslationRequest.cost_state == "reserved",
            )
            .with_for_update()
        )
        if not owner_request:
            return
        if owner_request.cost_ledger_id:
            ledger = db.scalar(
                select(GroupChatTranslationCostLedger)
                .where(GroupChatTranslationCostLedger.id == owner_request.cost_ledger_id)
                .with_for_update()
            )
            if ledger:
                ledger.reserved_variant_units = max(
                    0, ledger.reserved_variant_units - owner_request.reserved_variant_units
                )
                ledger.updated_at = now
        owner_request.cost_state = "released"
        owner_request.reserved_variant_units = 0
        owner_request.updated_at = now

    def _payload(self, item: GroupChatTranslation, translated_text: str | None = None) -> dict:
        if item.status == "final" and translated_text is None:
            if not item.translated_ciphertext or not item.translated_nonce:
                raise GroupServiceError("group_chat_translation_corrupt", 500)
            translated_text = self.crypto.decrypt_text(
                item.translated_ciphertext,
                item.translated_nonce,
                aad=f"group-chat-translation:{item.space_id}:{item.id}",
                version=item.encryption_version,
            )
        return {
            "id": item.id,
            "message_id": item.message_id,
            "source_language": item.source_language,
            "target_language": item.target_language,
            "state": item.status.upper(),
            "translated_text": translated_text or "",
            "provider_model": item.provider_model if item.status == "final" else "",
            "shared_variant": True,
            "cost_owner_membership_id": item.cost_owner_membership_id,
            "cost_state": item.cost_state,
            "final_at": _iso(item.final_at),
        }

    def _prepare(
        self,
        actor: GroupActor,
        space_id: str,
        message_id: str,
        idempotency_key: str,
    ) -> dict:
        if not self.settings.group_translation_enabled:
            raise GroupServiceError("group_translation_disabled", 503)
        key = str(idempotency_key or "").strip()
        if not 8 <= len(key) <= 128 or any(character.isspace() for character in key):
            raise GroupServiceError("idempotency_key_required", 400)
        with self.database.session() as db:
            try:
                with db.begin():
                    membership = self._membership(db, space_id, actor)
                    consent = db.scalar(
                        select(GroupTranslationConsent).where(
                            GroupTranslationConsent.space_id == space_id,
                            GroupTranslationConsent.membership_id == membership.id,
                        )
                    )
                    if (
                        not consent
                        or consent.status != "granted"
                        or consent.policy_version != self.settings.group_translation_policy_version
                    ):
                        raise GroupServiceError("group_translation_consent_required", 409)
                    profile = db.scalar(
                        select(GroupLanguageProfile).where(
                            GroupLanguageProfile.space_id == space_id,
                            GroupLanguageProfile.membership_id == membership.id,
                        )
                    )
                    target_language = (
                        profile.preferred_output_language if profile else actor.locale
                    )
                    message = db.scalar(
                        select(GroupMessage).where(
                            GroupMessage.id == message_id,
                            GroupMessage.space_id == space_id,
                            GroupMessage.status == "active",
                        )
                    )
                    if not message:
                        raise GroupServiceError("group_message_not_found", 404)
                    if message.content_type != "text":
                        raise GroupServiceError("group_chat_translation_text_only", 409)
                    original_text = self._message_text(message)
                    source_language = message.source_language
                    if source_language == target_language:
                        return {"skipped": True, "reason": "source_target_same"}
                    fingerprint = self._fingerprint(message, original_text)
                    by_key = db.scalar(
                        select(GroupChatTranslationRequest).where(
                            GroupChatTranslationRequest.requester_membership_id == membership.id,
                            GroupChatTranslationRequest.idempotency_key == key,
                        )
                    )
                    if by_key:
                        linked = db.get(GroupChatTranslation, by_key.translation_id)
                        if (
                            not linked
                            or linked.message_id != message.id
                            or linked.message_fingerprint != fingerprint
                            or linked.target_language != target_language
                        ):
                            raise GroupServiceError("idempotency_key_conflict", 409)
                        if linked.status == "failed":
                            raise GroupServiceError(
                                linked.failure_code or "group_translation_provider_failed", 503
                            )
                        return {
                            "item": linked,
                            "request": by_key,
                            "start_provider": False,
                            "idempotent": True,
                        }

                    shared_query = (
                        select(GroupChatTranslation)
                        .where(
                            GroupChatTranslation.message_id == message.id,
                            GroupChatTranslation.target_language == target_language,
                            GroupChatTranslation.message_fingerprint == fingerprint,
                        )
                        .with_for_update()
                    )
                    existing = db.scalar(shared_query)
                    now = _now()
                    start_provider = False
                    request_cost_state = "reuse"
                    if existing and existing.status == "pending":
                        lease_expires_at = existing.lease_expires_at
                        if lease_expires_at and lease_expires_at.tzinfo is None:
                            lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
                        if not lease_expires_at or lease_expires_at <= now:
                            start_provider = True
                    elif existing and existing.status == "failed":
                        start_provider = True

                    claim_token = ""
                    if existing and start_provider:
                        item = existing
                        self._release_reserved_cost(db, item, now)
                        claim_token = uuid4().hex
                        item.cost_owner_membership_id = membership.id
                        item.idempotency_key = self._provider_idempotency_key(
                            message.id, fingerprint, target_language
                        )
                        item.source_language = source_language
                        item.status = "pending"
                        item.cost_state = "reserved"
                        item.claim_token = claim_token
                        item.lease_expires_at = now + timedelta(seconds=90)
                        item.translated_ciphertext = None
                        item.translated_nonce = None
                        item.encryption_version = ""
                        item.provider_model = ""
                        item.provider_request_id = ""
                        item.failure_code = ""
                        item.final_at = None
                        item.updated_at = now
                        request_cost_state = "reserved"
                    elif existing:
                        item = existing
                    else:
                        claim_token = uuid4().hex
                        item = GroupChatTranslation(
                            id=str(uuid4()),
                            space_id=space_id,
                            message_id=message.id,
                            cost_owner_membership_id=membership.id,
                            idempotency_key=self._provider_idempotency_key(
                                message.id, fingerprint, target_language
                            ),
                            message_fingerprint=fingerprint,
                            source_language=source_language,
                            target_language=target_language,
                            status="pending",
                            cost_state="reserved",
                            claim_token=claim_token,
                            lease_expires_at=now + timedelta(seconds=90),
                        )
                        try:
                            with db.begin_nested():
                                db.add(item)
                                db.flush()
                            start_provider = True
                            request_cost_state = "reserved"
                        except IntegrityError:
                            item = db.scalar(shared_query)
                            if not item:
                                raise
                            claim_token = ""

                    cost_ledger = None
                    if start_provider:
                        cost_ledger = self._sync_cost_ledger(db, actor)
                        unavailable = (
                            cost_ledger.reserved_variant_units
                            + cost_ledger.settled_variant_units
                        )
                        if (
                            cost_ledger.limit_variant_units > 0
                            and unavailable >= cost_ledger.limit_variant_units
                        ):
                            raise GroupServiceError("group_chat_translation_quota_exceeded", 429)
                        cost_ledger.reserved_variant_units += 1
                        cost_ledger.updated_at = now

                    request_row = GroupChatTranslationRequest(
                        id=str(uuid4()),
                        translation_id=item.id,
                        requester_membership_id=membership.id,
                        cost_ledger_id=cost_ledger.id if cost_ledger else None,
                        idempotency_key=key,
                        cost_state=request_cost_state,
                        claim_token=claim_token,
                        reserved_variant_units=1 if start_provider else 0,
                    )
                    db.add(request_row)
                    self._audit(
                        db,
                        actor,
                        space_id,
                        "chat_translation.requested",
                        item.id,
                        metadata={
                            "message_id": message.id,
                            "source_language": source_language,
                            "target_language": target_language,
                            "shared_variant": True,
                            "cost_state": request_cost_state,
                        },
                    )
                    db.flush()
                    return {
                        "item": item,
                        "request": request_row,
                        "start_provider": start_provider,
                        "idempotent": not start_provider,
                        "claim_token": claim_token,
                        **({"original_text": original_text} if start_provider else {}),
                    }
            except IntegrityError as exc:
                recovered = self._recover_idempotent_request(
                    actor,
                    space_id,
                    message_id,
                    key,
                )
                if recovered:
                    return recovered
                raise GroupServiceError("group_chat_translation_conflict", 409) from exc

    def _recover_idempotent_request(
        self,
        actor: GroupActor,
        space_id: str,
        message_id: str,
        idempotency_key: str,
    ) -> dict | None:
        """Resolve the winner after a concurrent request-row unique conflict."""

        with self.database.session() as db:
            membership = self._membership(db, space_id, actor)
            message = db.scalar(
                select(GroupMessage).where(
                    GroupMessage.id == message_id,
                    GroupMessage.space_id == space_id,
                    GroupMessage.status == "active",
                )
            )
            if not message:
                raise GroupServiceError("group_message_not_found", 404)
            profile = db.scalar(
                select(GroupLanguageProfile).where(
                    GroupLanguageProfile.space_id == space_id,
                    GroupLanguageProfile.membership_id == membership.id,
                )
            )
            target_language = profile.preferred_output_language if profile else actor.locale
            fingerprint = self._fingerprint(message, self._message_text(message))
            request_row = db.scalar(
                select(GroupChatTranslationRequest).where(
                    GroupChatTranslationRequest.requester_membership_id == membership.id,
                    GroupChatTranslationRequest.idempotency_key == idempotency_key,
                )
            )
            item = db.get(GroupChatTranslation, request_row.translation_id) if request_row else None
            if (
                not request_row
                or not item
                or item.message_id != message.id
                or item.message_fingerprint != fingerprint
                or item.target_language != target_language
            ):
                return None
            if item.status == "failed":
                raise GroupServiceError(
                    item.failure_code or "group_translation_provider_failed", 503
                )
            return {
                "item": item,
                "request": request_row,
                "start_provider": False,
                "idempotent": True,
            }

    def _mark_failed(
        self,
        actor: GroupActor,
        space_id: str,
        translation_id: str,
        claim_token: str,
        failure_code: str,
    ) -> None:
        with self.database.session() as db:
            with db.begin():
                item = db.scalar(
                    select(GroupChatTranslation)
                    .where(
                        GroupChatTranslation.id == translation_id,
                        GroupChatTranslation.space_id == space_id,
                        GroupChatTranslation.claim_token == claim_token,
                    )
                    .with_for_update()
                )
                if not item or item.status != "pending":
                    return
                item.status = "failed"
                item.cost_state = "released"
                item.claim_token = ""
                item.lease_expires_at = None
                item.failure_code = failure_code[:80]
                item.updated_at = _now()
                self._release_reserved_cost(db, item, item.updated_at)
                self._audit(
                    db,
                    actor,
                    space_id,
                    "chat_translation.failed",
                    item.id,
                    outcome="failure",
                    metadata={"failure_code": item.failure_code},
                )

    def _finalize(
        self,
        actor: GroupActor,
        space_id: str,
        translation_id: str,
        claim_token: str,
        translated_text: str,
        provider_model: str,
        provider_request_id: str | None,
    ) -> dict:
        with self.database.session() as db:
            with db.begin():
                item = db.scalar(
                    select(GroupChatTranslation)
                    .where(
                        GroupChatTranslation.id == translation_id,
                        GroupChatTranslation.space_id == space_id,
                        GroupChatTranslation.claim_token == claim_token,
                    )
                    .with_for_update()
                )
                if not item:
                    raise GroupServiceError("group_chat_translation_not_found", 404)
                if item.status == "final":
                    return self._payload(item)
                if item.status != "pending":
                    raise GroupServiceError("group_chat_translation_not_pending", 409)
                message = db.get(GroupMessage, item.message_id)
                if not message or message.status != "active":
                    raise GroupServiceError("group_message_not_found", 404)
                current_text = self._message_text(message)
                if self._fingerprint(message, current_text) != item.message_fingerprint:
                    item.status = "failed"
                    item.failure_code = "group_message_changed_during_translation"
                    item.updated_at = _now()
                    raise GroupServiceError("group_message_changed_during_translation", 409)
                ciphertext, nonce, version = self.crypto.encrypt_text(
                    translated_text,
                    aad=f"group-chat-translation:{space_id}:{item.id}",
                )
                item.translated_ciphertext = ciphertext
                item.translated_nonce = nonce
                item.encryption_version = version
                item.provider_model = provider_model[:80]
                item.provider_request_id = str(provider_request_id or "")[:128]
                item.failure_code = ""
                item.status = "final"
                item.cost_state = "settled"
                item.claim_token = ""
                item.lease_expires_at = None
                item.final_at = _now()
                item.updated_at = item.final_at
                owner_request = db.scalar(
                    select(GroupChatTranslationRequest)
                    .where(
                        GroupChatTranslationRequest.translation_id == item.id,
                        GroupChatTranslationRequest.cost_state == "reserved",
                    )
                    .with_for_update()
                )
                if not owner_request:
                    raise GroupServiceError("group_translation_cost_reservation_missing", 409)
                if owner_request.cost_ledger_id:
                    ledger = db.scalar(
                        select(GroupChatTranslationCostLedger)
                        .where(GroupChatTranslationCostLedger.id == owner_request.cost_ledger_id)
                        .with_for_update()
                    )
                    if not ledger:
                        raise GroupServiceError("group_translation_cost_ledger_missing", 409)
                    ledger.reserved_variant_units = max(
                        0, ledger.reserved_variant_units - owner_request.reserved_variant_units
                    )
                    ledger.settled_variant_units += owner_request.reserved_variant_units
                    ledger.updated_at = item.final_at
                owner_request.cost_state = "settled"
                owner_request.settled_variant_units = owner_request.reserved_variant_units
                owner_request.reserved_variant_units = 0
                owner_request.updated_at = item.final_at
                self._audit(
                    db,
                    actor,
                    space_id,
                    "chat_translation.final_persisted",
                    item.id,
                    metadata={
                        "message_id": item.message_id,
                        "state": "FINAL",
                        "target_language": item.target_language,
                    },
                )
                return self._payload(item, translated_text)

    async def _wait_for_terminal(self, space_id: str, translation_id: str) -> dict | None:
        deadline = time.monotonic() + min(
            30.0, max(1.0, self.settings.timeblock_timeout_seconds * 2)
        )
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            with self.database.session() as db:
                item = db.scalar(
                    select(GroupChatTranslation).where(
                        GroupChatTranslation.id == translation_id,
                        GroupChatTranslation.space_id == space_id,
                    )
                )
                if not item:
                    raise GroupServiceError("group_chat_translation_not_found", 404)
                if item.status == "final":
                    return self._payload(item)
                if item.status == "failed":
                    raise GroupServiceError(
                        item.failure_code or "group_translation_provider_failed", 503
                    )
        return None

    async def translate(
        self,
        actor: GroupActor,
        space_id: str,
        message_id: str,
        idempotency_key: str,
    ) -> dict:
        prepared = self._prepare(actor, space_id, message_id, idempotency_key)
        if prepared.get("skipped"):
            return {"translation": None, "skipped": True, "reason": prepared["reason"]}
        item = prepared["item"]
        if not prepared["start_provider"]:
            if item.status == "final":
                return {"translation": self._payload(item), "idempotent": True}
            completed = await self._wait_for_terminal(space_id, item.id)
            if completed:
                return {"translation": completed, "idempotent": True}
            return {"translation": self._payload(item), "pending": True, "idempotent": True}
        try:
            result = await self.provider.translate_text(
                source_text=prepared["original_text"],
                source_language=item.source_language,
                target_language=item.target_language,
                principal_id=actor.key,
                idempotency_key=item.idempotency_key,
            )
        except asyncio.CancelledError:
            self._mark_failed(
                actor,
                space_id,
                item.id,
                prepared["claim_token"],
                "group_translation_provider_cancelled",
            )
            raise
        except GroupTranslationProviderError as exc:
            code = str(exc)
            self._mark_failed(actor, space_id, item.id, prepared["claim_token"], code)
            status_code = 503 if code in {
                "group_translation_disabled",
                "group_translation_provider_not_configured",
                "group_translation_provider_unavailable",
            } else 502
            raise GroupServiceError(code, status_code) from exc
        except Exception as exc:
            self._mark_failed(
                actor,
                space_id,
                item.id,
                prepared["claim_token"],
                "group_translation_provider_unavailable",
            )
            raise GroupServiceError(
                "group_translation_provider_unavailable", 503
            ) from exc
        try:
            payload = self._finalize(
                actor,
                space_id,
                item.id,
                prepared["claim_token"],
                result.text,
                result.model,
                result.request_id,
            )
        except GroupServiceError as exc:
            if exc.code in {
                "group_message_not_found",
                "group_message_changed_during_translation",
            }:
                self._mark_failed(
                    actor, space_id, item.id, prepared["claim_token"], exc.code
                )
            raise
        except Exception as exc:
            self._mark_failed(
                actor,
                space_id,
                item.id,
                prepared["claim_token"],
                "group_translation_finalize_failed",
            )
            raise GroupServiceError("group_translation_finalize_failed", 500) from exc
        return {"translation": payload, "idempotent": False}

    def history(self, actor: GroupActor, space_id: str, limit: int) -> list[dict]:
        with self.database.session() as db:
            membership = self._membership(db, space_id, actor)
            profile = db.scalar(
                select(GroupLanguageProfile).where(
                    GroupLanguageProfile.space_id == space_id,
                    GroupLanguageProfile.membership_id == membership.id,
                )
            )
            target_language = profile.preferred_output_language if profile else actor.locale
            rows = list(
                db.scalars(
                    select(GroupChatTranslation)
                    .where(
                        GroupChatTranslation.space_id == space_id,
                        GroupChatTranslation.status == "final",
                        GroupChatTranslation.target_language == target_language,
                    )
                    .order_by(GroupChatTranslation.final_at.desc())
                    .limit(limit)
                ).all()
            )
            payloads = []
            for item in rows:
                message = db.get(GroupMessage, item.message_id)
                if not message or message.status != "active":
                    continue
                if self._fingerprint(message, self._message_text(message)) != item.message_fingerprint:
                    continue
                payloads.append(self._payload(item))
            return payloads
