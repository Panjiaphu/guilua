from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.db import Database
from app.group_v3.auth import GroupActor
from app.group_v3.crypto import GroupCrypto
from app.models import (
    GroupAttachment,
    GroupAuditEvent,
    GroupIdempotencyRecord,
    GroupMediaParticipant,
    GroupMediaSession,
    GroupMembership,
    GroupMessage,
    GroupMessagePin,
    GroupMessageReaction,
    GroupRadioBurst,
    GroupRadioParticipant,
    GroupRadioProcessingJob,
    GroupRadioSession,
    GroupSpace,
    GroupTtsJob,
)


class GroupServiceError(RuntimeError):
    def __init__(self, code: str, status_code: int = 400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class GroupService:
    def __init__(self, database: Database, crypto: GroupCrypto, event_broker=None):
        self.database = database
        self.crypto = crypto
        self.event_broker = event_broker

    def _enqueue(self, db, space_id: str, event_type: str, resource_id: object = "") -> None:
        if self.event_broker:
            self.event_broker.enqueue_in_transaction(
                db, space_id, event_type, resource_id=resource_id
            )

    @staticmethod
    def _membership(db, space_id: str, actor: GroupActor) -> GroupMembership | None:
        return db.scalar(
            select(GroupMembership).where(
                GroupMembership.space_id == space_id,
                GroupMembership.principal_type == actor.principal_type,
                GroupMembership.principal_id == actor.principal_id,
                GroupMembership.principal_user_id == actor.principal_user_id,
                GroupMembership.status == "active",
            )
        )

    def _require_membership(
        self,
        db,
        space_id: str,
        actor: GroupActor,
        *,
        roles: set[str] | None = None,
    ) -> GroupMembership:
        membership = self._membership(db, space_id, actor)
        if not membership:
            raise GroupServiceError("group_membership_required", 403)
        if roles and membership.role not in roles:
            raise GroupServiceError("group_permission_denied", 403)
        return membership

    @staticmethod
    def _space_payload(space: GroupSpace, membership: GroupMembership | None = None) -> dict:
        return {
            "id": space.id,
            "title": space.title,
            "description": space.description,
            "lifecycle_status": space.lifecycle_status,
            "version": space.version,
            "my_role": membership.role if membership else "",
            "created_at": _iso(space.created_at),
            "updated_at": _iso(space.updated_at),
        }

    @staticmethod
    def _membership_payload(item: GroupMembership) -> dict:
        return {
            "id": item.id,
            "space_id": item.space_id,
            "principal_type": item.principal_type,
            "principal_id": item.principal_id,
            "principal_user_id": item.principal_user_id,
            "display_name": item.display_name,
            "role": item.role,
            "status": item.status,
            "joined_at": _iso(item.joined_at),
            "left_at": _iso(item.left_at),
        }

    @staticmethod
    def _audit(
        db,
        actor: GroupActor,
        space_id: str,
        event_type: str,
        *,
        resource_type: str = "",
        resource_id: str = "",
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
                resource_type=resource_type,
                resource_id=resource_id,
                metadata_json=_canonical_json(metadata or {}),
            )
        )

    @staticmethod
    def _idempotency_key(value: str | None) -> str:
        normalized = str(value or "").strip()
        if not 8 <= len(normalized) <= 128 or any(character.isspace() for character in normalized):
            raise GroupServiceError("idempotency_key_required", 400)
        return normalized

    @staticmethod
    def _idempotency_lookup(db, endpoint: str, actor: GroupActor, key: str, request_hash: str) -> dict | None:
        row = db.scalar(
            select(GroupIdempotencyRecord).where(
                GroupIdempotencyRecord.endpoint == endpoint,
                GroupIdempotencyRecord.actor_key == actor.key,
                GroupIdempotencyRecord.idempotency_key == key,
            )
        )
        if not row:
            return None
        if row.request_hash != request_hash:
            raise GroupServiceError("idempotency_payload_mismatch", 409)
        try:
            payload = json.loads(row.response_json)
        except json.JSONDecodeError as exc:
            raise GroupServiceError("idempotency_record_invalid", 500) from exc
        payload["idempotent"] = True
        return payload

    @staticmethod
    def _idempotency_store(db, endpoint: str, actor: GroupActor, key: str, request_hash: str, payload: dict, status_code: int) -> None:
        db.add(
            GroupIdempotencyRecord(
                id=str(uuid4()),
                endpoint=endpoint,
                actor_key=actor.key,
                idempotency_key=key,
                request_hash=request_hash,
                status_code=status_code,
                response_json=_canonical_json(payload),
            )
        )

    def list_spaces(self, actor: GroupActor) -> list[dict]:
        with self.database.session() as db:
            rows = db.execute(
                select(GroupSpace, GroupMembership)
                .join(GroupMembership, GroupMembership.space_id == GroupSpace.id)
                .where(
                    GroupMembership.principal_type == actor.principal_type,
                    GroupMembership.principal_id == actor.principal_id,
                    GroupMembership.principal_user_id == actor.principal_user_id,
                    GroupMembership.status == "active",
                    GroupSpace.lifecycle_status != "deleted",
                )
                .order_by(GroupSpace.updated_at.desc(), GroupSpace.id)
            ).all()
            return [self._space_payload(space, membership) for space, membership in rows]

    def create_space(self, actor: GroupActor, values: dict, idempotency_key: str | None) -> dict:
        key = self._idempotency_key(idempotency_key)
        request_hash = hashlib.sha256(_canonical_json(values).encode("utf-8")).hexdigest()
        endpoint = "group.spaces.create"
        with self.database.session() as db:
            with db.begin():
                existing = self._idempotency_lookup(db, endpoint, actor, key, request_hash)
                if existing:
                    return existing
                space = GroupSpace(
                    id=str(uuid4()),
                    title=values["title"],
                    description=values.get("description") or "",
                    created_by_type=actor.principal_type,
                    created_by_id=actor.principal_id,
                    created_by_user_id=actor.principal_user_id,
                )
                membership = GroupMembership(
                    id=str(uuid4()),
                    space_id=space.id,
                    principal_type=actor.principal_type,
                    principal_id=actor.principal_id,
                    principal_user_id=actor.principal_user_id,
                    display_name=actor.display_name,
                    role="owner",
                    status="active",
                )
                # group_audit_events.space_id has a real FK to group_spaces.
                # Flush the parent before adding dependent rows so PostgreSQL
                # cannot order the audit INSERT before the new space.
                db.add(space)
                db.flush()
                db.add(membership)
                self._audit(db, actor, space.id, "space.created", resource_type="space", resource_id=space.id)
                db.flush()
                db.refresh(space)
                db.refresh(membership)
                payload = {"space": self._space_payload(space, membership), "idempotent": False}
                self._idempotency_store(db, endpoint, actor, key, request_hash, payload, 201)
                self._enqueue(db, space.id, "space.created", space.id)
                return payload

    def get_space(self, actor: GroupActor, space_id: str) -> dict:
        with self.database.session() as db:
            membership = self._require_membership(db, space_id, actor)
            space = db.get(GroupSpace, space_id)
            if not space or space.lifecycle_status == "deleted":
                raise GroupServiceError("group_space_not_found", 404)
            return self._space_payload(space, membership)

    def update_space(self, actor: GroupActor, space_id: str, values: dict) -> dict:
        with self.database.session() as db:
            with db.begin():
                membership = self._require_membership(db, space_id, actor, roles={"owner", "admin"})
                space = db.get(GroupSpace, space_id)
                if not space or space.lifecycle_status == "deleted":
                    raise GroupServiceError("group_space_not_found", 404)
                if int(values["version"]) != space.version:
                    raise GroupServiceError("group_space_version_conflict", 409)
                if values.get("lifecycle_status") is not None and membership.role != "owner":
                    raise GroupServiceError("group_lifecycle_update_denied", 403)
                for key in ("title", "description", "lifecycle_status"):
                    if values.get(key) is not None:
                        setattr(space, key, values[key])
                space.version += 1
                space.updated_at = _now()
                self._audit(db, actor, space_id, "space.updated", resource_type="space", resource_id=space_id)
                self._enqueue(db, space_id, "space.updated", space_id)
                return self._space_payload(space, membership)

    def transfer_ownership(
        self,
        actor: GroupActor,
        space_id: str,
        target_membership_id: str,
        version: int,
    ) -> dict:
        """Atomically move the sole active owner role to another member."""

        with self.database.session() as db:
            try:
                with db.begin():
                    current_owner = self._require_membership(db, space_id, actor, roles={"owner"})
                    space = db.get(GroupSpace, space_id)
                    if not space or space.lifecycle_status == "deleted":
                        raise GroupServiceError("group_space_not_found", 404)
                    if int(version) != space.version:
                        raise GroupServiceError("group_space_version_conflict", 409)
                    if target_membership_id == current_owner.id:
                        raise GroupServiceError("group_transfer_target_required", 400)
                    target = db.get(GroupMembership, target_membership_id)
                    if not target or target.space_id != space_id or target.status != "active":
                        raise GroupServiceError("group_transfer_target_invalid", 404)
                    # Demote first, then promote. The partial unique index prevents
                    # any concurrent transaction from creating a second owner.
                    current_owner.role = "admin"
                    current_owner.updated_at = _now()
                    db.flush()
                    target.role = "owner"
                    target.updated_at = _now()
                    space.version += 1
                    space.updated_at = _now()
                    self._audit(
                        db,
                        actor,
                        space_id,
                        "ownership.transferred",
                        resource_type="membership",
                        resource_id=target.id,
                        metadata={"from_membership_id": current_owner.id, "to_membership_id": target.id},
                    )
                    self._enqueue(db, space_id, "ownership.transferred", target.id)
                    return self._space_payload(space, current_owner)
            except IntegrityError as exc:
                raise GroupServiceError("group_owner_conflict", 409) from exc

    def delete_space(self, actor: GroupActor, space_id: str, version: int) -> dict:
        """Soft-delete a Group and stop all durable participation in one transaction."""

        with self.database.session() as db:
            with db.begin():
                owner = self._require_membership(db, space_id, actor, roles={"owner"})
                space = db.get(GroupSpace, space_id)
                if not space or space.lifecycle_status == "deleted":
                    raise GroupServiceError("group_space_not_found", 404)
                if int(version) != space.version:
                    raise GroupServiceError("group_space_version_conflict", 409)
                now = _now()
                space.lifecycle_status = "deleted"
                space.version += 1
                space.updated_at = now
                db.execute(
                    update(GroupMembership)
                    .where(GroupMembership.space_id == space_id, GroupMembership.status == "active")
                    .values(status="removed", left_at=now, updated_at=now)
                )
                db.execute(
                    update(GroupMediaParticipant)
                    .where(GroupMediaParticipant.session_id.in_(select(GroupMediaSession.id).where(GroupMediaSession.space_id == space_id)))
                    .values(invite_status="left", connection_status="failed", connection_error_code="space_deleted", left_at=now, updated_at=now)
                )
                db.execute(
                    update(GroupMediaSession)
                    .where(GroupMediaSession.space_id == space_id, GroupMediaSession.status != "ended")
                    .values(status="ended", ended_at=now, end_reason="space_deleted", updated_at=now)
                )
                db.execute(
                    update(GroupRadioParticipant)
                    .where(GroupRadioParticipant.radio_session_id.in_(select(GroupRadioSession.id).where(GroupRadioSession.space_id == space_id)))
                    .values(status="removed", device_state="lost", left_at=now, device_lost_at=now, updated_at=now)
                )
                db.execute(
                    update(GroupRadioSession)
                    .where(GroupRadioSession.space_id == space_id, GroupRadioSession.status != "ended")
                    .values(status="ended", ended_at=now, ended_by_membership_id=owner.id, updated_at=now)
                )
                self._audit(db, actor, space_id, "space.deleted", resource_type="space", resource_id=space_id)
                self._enqueue(db, space_id, "space.deleted", space_id)
                return {"id": space_id, "lifecycle_status": "deleted", "version": space.version}

    def list_members(self, actor: GroupActor, space_id: str) -> list[dict]:
        with self.database.session() as db:
            self._require_membership(db, space_id, actor)
            items = db.scalars(
                select(GroupMembership)
                .where(GroupMembership.space_id == space_id)
                .order_by(GroupMembership.status, GroupMembership.role, GroupMembership.joined_at)
            ).all()
            return [self._membership_payload(item) for item in items]

    def add_member(self, actor: GroupActor, space_id: str, values: dict) -> dict:
        with self.database.session() as db:
            try:
                with db.begin():
                    self._require_membership(db, space_id, actor, roles={"owner", "admin"})
                    existing = db.scalar(
                        select(GroupMembership).where(
                            GroupMembership.space_id == space_id,
                            GroupMembership.principal_type == values["principal_type"],
                            GroupMembership.principal_id == values["principal_id"],
                            GroupMembership.principal_user_id == values["principal_user_id"],
                        )
                    )
                    if existing:
                        existing.display_name = values["display_name"]
                        existing.role = values["role"]
                        existing.status = "active"
                        existing.left_at = None
                        existing.updated_at = _now()
                        item = existing
                    else:
                        item = GroupMembership(
                            id=str(uuid4()),
                            space_id=space_id,
                            principal_type=values["principal_type"],
                            principal_id=values["principal_id"],
                            principal_user_id=values["principal_user_id"],
                            display_name=values["display_name"],
                            role=values["role"],
                            status="active",
                        )
                        db.add(item)
                    self._audit(db, actor, space_id, "membership.upserted", resource_type="membership", resource_id=item.id, metadata={"role": item.role})
                    self._enqueue(db, space_id, "membership.created", item.id)
                    return self._membership_payload(item)
            except IntegrityError as exc:
                raise GroupServiceError("group_membership_conflict", 409) from exc

    def update_member(self, actor: GroupActor, space_id: str, membership_id: str, values: dict) -> dict:
        with self.database.session() as db:
            with db.begin():
                actor_membership = self._require_membership(
                    db, space_id, actor, roles={"owner", "admin"}
                )
                item = db.get(GroupMembership, membership_id)
                if not item or item.space_id != space_id:
                    raise GroupServiceError("group_membership_not_found", 404)
                if item.role == "owner":
                    raise GroupServiceError("group_owner_immutable", 409)
                if actor_membership.role == "admin" and (
                    item.role != "member" or values.get("role") is not None
                ):
                    raise GroupServiceError("group_admin_member_only", 403)
                if values.get("role") is not None:
                    if actor_membership.role != "owner":
                        raise GroupServiceError("group_role_update_denied", 403)
                    item.role = values["role"]
                if values.get("status") is not None:
                    if values["status"] == "active" and item.status != "active":
                        raise GroupServiceError("group_reinvite_required", 409)
                    item.status = values["status"]
                    item.left_at = _now() if item.status != "active" else None
                    if item.status == "removed":
                        now = _now()
                        db.execute(
                            update(GroupMediaParticipant)
                            .where(
                                GroupMediaParticipant.membership_id == item.id,
                                GroupMediaParticipant.invite_status.in_({"invited", "joined"}),
                            )
                            .values(invite_status="left", left_at=now, updated_at=now)
                        )
                        db.execute(
                            update(GroupRadioParticipant)
                            .where(
                                GroupRadioParticipant.membership_id == item.id,
                                GroupRadioParticipant.status.in_({"invited", "joined"}),
                            )
                            .values(
                                status="removed",
                                device_state="lost",
                                left_at=now,
                                device_lost_at=now,
                                updated_at=now,
                            )
                        )
                        active_bursts = select(GroupRadioBurst.id).where(
                            GroupRadioBurst.speaker_membership_id == item.id,
                            GroupRadioBurst.state.in_({"talking", "finalizing"}),
                        )
                        db.execute(
                            update(GroupRadioProcessingJob)
                            .where(
                                GroupRadioProcessingJob.burst_id.in_(active_bursts),
                                GroupRadioProcessingJob.status.in_({"ready", "processing"}),
                            )
                            .values(
                                status="suppressed",
                                failure_code="membership_removed",
                                updated_at=now,
                            )
                        )
                        db.execute(
                            update(GroupRadioBurst)
                            .where(
                                GroupRadioBurst.speaker_membership_id == item.id,
                                GroupRadioBurst.state.in_({"talking", "finalizing"}),
                            )
                            .values(
                                state="device_lost",
                                stop_reason="membership_removed",
                                stopped_at=now,
                                updated_at=now,
                            )
                        )
                        db.execute(
                            update(GroupTtsJob)
                            .where(
                                GroupTtsJob.recipient_membership_id == item.id,
                                GroupTtsJob.status.in_({"pending", "claimed"}),
                            )
                            .values(status="suppressed", failure_code="membership_removed")
                        )
                item.updated_at = _now()
                self._audit(db, actor, space_id, "membership.updated", resource_type="membership", resource_id=item.id, metadata={"role": item.role, "status": item.status})
                self._enqueue(db, space_id, "membership.updated", item.id)
                return self._membership_payload(item)

    def radio_session_ids_for_membership(self, membership_id: str) -> list[str]:
        with self.database.session() as db:
            return list(
                db.scalars(
                    select(GroupRadioParticipant.radio_session_id).where(
                        GroupRadioParticipant.membership_id == membership_id
                    )
                ).all()
            )

    def _message_payloads(self, db, actor: GroupActor, messages: list[GroupMessage]) -> list[dict]:
        if not messages:
            return []
        ids = [item.id for item in messages]
        reactions = db.scalars(select(GroupMessageReaction).where(GroupMessageReaction.message_id.in_(ids))).all()
        pins = set(db.scalars(select(GroupMessagePin.message_id).where(GroupMessagePin.message_id.in_(ids))).all())
        attachments = db.scalars(
            select(GroupAttachment).where(
                GroupAttachment.message_id.in_(ids),
                GroupAttachment.status == "attached",
            )
        ).all()
        reactions_by_message: dict[str, dict[str, dict]] = defaultdict(dict)
        for item in reactions:
            state = reactions_by_message[item.message_id].setdefault(
                item.reaction,
                {"reaction": item.reaction, "count": 0, "reacted_by_me": False},
            )
            state["count"] += 1
            state["reacted_by_me"] = state["reacted_by_me"] or (
                item.principal_type == actor.principal_type
                and item.principal_id == actor.principal_id
                and item.principal_user_id == actor.principal_user_id
            )
        attachments_by_message: dict[str, list[dict]] = defaultdict(list)
        for item in attachments:
            attachments_by_message[str(item.message_id)].append(
                {
                    "id": item.id,
                    "name": item.original_name,
                    "mime_type": item.mime_type,
                    "size_bytes": item.size_bytes,
                    "download_url": f"/api/group/spaces/{item.space_id}/attachments/{item.id}",
                    "inline_url": f"/api/group/spaces/{item.space_id}/attachments/{item.id}/inline",
                    "is_image": item.mime_type in {"image/jpeg", "image/png", "image/gif", "image/webp"},
                    "is_audio": item.mime_type.startswith("audio/"),
                    "is_video": item.mime_type.startswith("video/"),
                }
            )
        payloads = []
        for item in messages:
            content = ""
            if item.status == "active":
                content = self.crypto.decrypt_text(
                    item.content_ciphertext,
                    item.content_nonce,
                    aad=f"group-message:{item.space_id}:{item.id}",
                    version=item.encryption_version,
                )
            payloads.append(
                {
                    "id": item.id,
                    "space_id": item.space_id,
                    "sequence": item.sequence,
                    "sender": {
                        "type": item.sender_type,
                        "id": item.sender_id,
                        "user_id": item.sender_user_id,
                        "display_name": item.sender_display_name,
                    },
                    "content": content,
                    "source_language": item.source_language,
                    "content_type": "tombstone" if item.status == "deleted" else item.content_type,
                    "reply_to_id": item.reply_to_id,
                    "reactions": list(reactions_by_message[item.id].values()),
                    "pinned": item.id in pins,
                    "attachments": attachments_by_message[item.id],
                    "created_at": _iso(item.created_at),
                    "edited_at": _iso(item.edited_at),
                    "deleted_at": _iso(item.deleted_at),
                }
            )
        return payloads

    def list_messages(self, actor: GroupActor, space_id: str, *, before: int | None, limit: int) -> list[dict]:
        with self.database.session() as db:
            self._require_membership(db, space_id, actor)
            query = select(GroupMessage).where(GroupMessage.space_id == space_id)
            if before is not None:
                query = query.where(GroupMessage.sequence < before)
            messages = list(db.scalars(query.order_by(GroupMessage.sequence.desc()).limit(limit)).all())
            messages.reverse()
            return self._message_payloads(db, actor, messages)

    def create_message(self, actor: GroupActor, space_id: str, values: dict, idempotency_key: str | None) -> dict:
        key = self._idempotency_key(idempotency_key)
        request_hash = hashlib.sha256(_canonical_json(values).encode("utf-8")).hexdigest()
        endpoint = f"group.messages.create:{space_id}"
        message_id = str(uuid4())
        ciphertext, nonce, version = self.crypto.encrypt_text(
            values["content"], aad=f"group-message:{space_id}:{message_id}"
        )
        with self.database.session() as db:
            try:
                with db.begin():
                    self._require_membership(db, space_id, actor)
                    existing = self._idempotency_lookup(db, endpoint, actor, key, request_hash)
                    if existing:
                        return existing
                    if values.get("reply_to_id"):
                        reply = db.get(GroupMessage, values["reply_to_id"])
                        if not reply or reply.space_id != space_id:
                            raise GroupServiceError("group_reply_not_found", 404)
                    attachment_ids = values.get("attachment_ids") or []
                    attachment_rows = []
                    if attachment_ids:
                        attachment_rows = list(
                            db.scalars(
                                select(GroupAttachment).where(
                                    GroupAttachment.id.in_(attachment_ids),
                                    GroupAttachment.space_id == space_id,
                                    GroupAttachment.uploader_type == actor.principal_type,
                                    GroupAttachment.uploader_id == actor.principal_id,
                                    GroupAttachment.uploader_user_id == actor.principal_user_id,
                                    GroupAttachment.status == "pending",
                                )
                            ).all()
                        )
                        if len(attachment_rows) != len(attachment_ids):
                            raise GroupServiceError("group_attachment_not_available", 409)
                    sequence = db.execute(
                        update(GroupSpace)
                        .where(GroupSpace.id == space_id, GroupSpace.lifecycle_status == "active")
                        .values(message_sequence=GroupSpace.message_sequence + 1, updated_at=_now())
                        .returning(GroupSpace.message_sequence)
                    ).scalar_one_or_none()
                    if sequence is None:
                        raise GroupServiceError("group_space_not_active", 409)
                    message = GroupMessage(
                        id=message_id,
                        space_id=space_id,
                        sequence=sequence,
                        sender_type=actor.principal_type,
                        sender_id=actor.principal_id,
                        sender_user_id=actor.principal_user_id,
                        sender_display_name=actor.display_name,
                        client_message_id=values["client_message_id"],
                        source_language=values.get("source_language") or actor.locale,
                        content_type=values["content_type"],
                        content_ciphertext=ciphertext,
                        content_nonce=nonce,
                        encryption_version=version,
                        reply_to_id=values.get("reply_to_id"),
                    )
                    db.add(message)
                    db.flush()
                    for attachment in attachment_rows:
                        attachment.message_id = message.id
                        attachment.status = "attached"
                    self._audit(db, actor, space_id, "message.created", resource_type="message", resource_id=message.id, metadata={"sequence": sequence, "attachment_count": len(attachment_rows)})
                    db.flush()
                    payload = {"message": self._message_payloads(db, actor, [message])[0], "idempotent": False}
                    self._idempotency_store(db, endpoint, actor, key, request_hash, payload, 201)
                    self._enqueue(db, space_id, "message.created", message.id)
                    return payload
            except IntegrityError as exc:
                raise GroupServiceError("group_message_conflict", 409) from exc

    def update_message(self, actor: GroupActor, space_id: str, message_id: str, content: str) -> dict:
        ciphertext, nonce, version = self.crypto.encrypt_text(content, aad=f"group-message:{space_id}:{message_id}")
        with self.database.session() as db:
            with db.begin():
                membership = self._require_membership(db, space_id, actor)
                message = db.get(GroupMessage, message_id)
                if not message or message.space_id != space_id or message.status != "active":
                    raise GroupServiceError("group_message_not_found", 404)
                is_sender = (
                    message.sender_type == actor.principal_type
                    and message.sender_id == actor.principal_id
                    and message.sender_user_id == actor.principal_user_id
                )
                if not is_sender and membership.role not in {"owner", "admin"}:
                    raise GroupServiceError("group_permission_denied", 403)
                message.content_ciphertext = ciphertext
                message.content_nonce = nonce
                message.encryption_version = version
                message.edited_at = _now()
                self._audit(db, actor, space_id, "message.updated", resource_type="message", resource_id=message.id)
                self._enqueue(db, space_id, "message.updated", message.id)
                return self._message_payloads(db, actor, [message])[0]

    def delete_message(self, actor: GroupActor, space_id: str, message_id: str) -> dict:
        with self.database.session() as db:
            with db.begin():
                membership = self._require_membership(db, space_id, actor)
                message = db.get(GroupMessage, message_id)
                if not message or message.space_id != space_id:
                    raise GroupServiceError("group_message_not_found", 404)
                is_sender = (
                    message.sender_type == actor.principal_type
                    and message.sender_id == actor.principal_id
                    and message.sender_user_id == actor.principal_user_id
                )
                if not is_sender and membership.role not in {"owner", "admin"}:
                    raise GroupServiceError("group_permission_denied", 403)
                if message.status != "deleted":
                    ciphertext, nonce, version = self.crypto.encrypt_text("", aad=f"group-message:{space_id}:{message_id}")
                    message.content_ciphertext = ciphertext
                    message.content_nonce = nonce
                    message.encryption_version = version
                    message.status = "deleted"
                    message.deleted_at = _now()
                    db.execute(delete(GroupMessageReaction).where(GroupMessageReaction.message_id == message_id))
                    db.execute(delete(GroupMessagePin).where(GroupMessagePin.message_id == message_id))
                    self._audit(db, actor, space_id, "message.deleted", resource_type="message", resource_id=message.id)
                    self._enqueue(db, space_id, "message.deleted", message.id)
                return {"message_id": message_id, "deleted": True}

    def set_reaction(self, actor: GroupActor, space_id: str, message_id: str, reaction: str, enabled: bool) -> dict:
        with self.database.session() as db:
            try:
                with db.begin():
                    self._require_membership(db, space_id, actor)
                    message = db.get(GroupMessage, message_id)
                    if not message or message.space_id != space_id or message.status != "active":
                        raise GroupServiceError("group_message_not_found", 404)
                    conditions = (
                        GroupMessageReaction.message_id == message_id,
                        GroupMessageReaction.principal_type == actor.principal_type,
                        GroupMessageReaction.principal_id == actor.principal_id,
                        GroupMessageReaction.principal_user_id == actor.principal_user_id,
                        GroupMessageReaction.reaction == reaction,
                    )
                    existing = db.scalar(select(GroupMessageReaction).where(*conditions))
                    if enabled and not existing:
                        db.add(GroupMessageReaction(id=str(uuid4()), message_id=message_id, principal_type=actor.principal_type, principal_id=actor.principal_id, principal_user_id=actor.principal_user_id, reaction=reaction))
                    elif not enabled and existing:
                        db.delete(existing)
                    self._audit(db, actor, space_id, "reaction.added" if enabled else "reaction.removed", resource_type="message", resource_id=message_id, metadata={"reaction": reaction})
                    self._enqueue(db, space_id, "message.reaction", message_id)
                    db.flush()
                    return {"message": self._message_payloads(db, actor, [message])[0]}
            except IntegrityError as exc:
                raise GroupServiceError("group_reaction_conflict", 409) from exc

    def set_pin(self, actor: GroupActor, space_id: str, message_id: str, enabled: bool) -> dict:
        with self.database.session() as db:
            try:
                with db.begin():
                    self._require_membership(db, space_id, actor)
                    message = db.get(GroupMessage, message_id)
                    if not message or message.space_id != space_id or message.status != "active":
                        raise GroupServiceError("group_message_not_found", 404)
                    existing = db.scalar(select(GroupMessagePin).where(GroupMessagePin.space_id == space_id, GroupMessagePin.message_id == message_id))
                    if enabled and not existing:
                        db.add(GroupMessagePin(id=str(uuid4()), space_id=space_id, message_id=message_id, pinned_by_type=actor.principal_type, pinned_by_id=actor.principal_id, pinned_by_user_id=actor.principal_user_id))
                    elif not enabled and existing:
                        db.delete(existing)
                    self._audit(db, actor, space_id, "message.pinned" if enabled else "message.unpinned", resource_type="message", resource_id=message_id)
                    self._enqueue(db, space_id, "message.pin", message_id)
                    return {"message_id": message_id, "pinned": enabled}
            except IntegrityError as exc:
                raise GroupServiceError("group_pin_conflict", 409) from exc

    def list_pins(self, actor: GroupActor, space_id: str) -> list[dict]:
        with self.database.session() as db:
            self._require_membership(db, space_id, actor)
            messages = list(
                db.scalars(
                    select(GroupMessage)
                    .join(GroupMessagePin, GroupMessagePin.message_id == GroupMessage.id)
                    .where(GroupMessagePin.space_id == space_id, GroupMessage.status == "active")
                    .order_by(GroupMessagePin.created_at.desc())
                ).all()
            )
            return self._message_payloads(db, actor, messages)

    def create_attachment(self, actor: GroupActor, space_id: str, *, name: str, mime_type: str, payload: bytes) -> dict:
        attachment_id = str(uuid4())
        ciphertext, nonce, version = self.crypto.encrypt(payload, aad=f"group-attachment:{space_id}:{attachment_id}")
        with self.database.session() as db:
            with db.begin():
                self._require_membership(db, space_id, actor)
                item = GroupAttachment(id=attachment_id, space_id=space_id, uploader_type=actor.principal_type, uploader_id=actor.principal_id, uploader_user_id=actor.principal_user_id, original_name=name, mime_type=mime_type, size_bytes=len(payload), payload_ciphertext=ciphertext, payload_nonce=nonce, encryption_version=version, status="pending")
                db.add(item)
                self._audit(db, actor, space_id, "attachment.created", resource_type="attachment", resource_id=item.id, metadata={"size_bytes": len(payload), "mime_type": mime_type})
                return {"id": item.id, "name": item.original_name, "mime_type": item.mime_type, "size_bytes": item.size_bytes, "status": item.status}

    def get_attachment(self, actor: GroupActor, space_id: str, attachment_id: str) -> tuple[dict, bytes]:
        with self.database.session() as db:
            self._require_membership(db, space_id, actor)
            item = db.get(GroupAttachment, attachment_id)
            if not item or item.space_id != space_id or item.status == "deleted":
                raise GroupServiceError("group_attachment_not_found", 404)
            payload = self.crypto.decrypt(item.payload_ciphertext, item.payload_nonce, aad=f"group-attachment:{space_id}:{attachment_id}", version=item.encryption_version)
            return {"name": item.original_name, "mime_type": item.mime_type, "size_bytes": item.size_bytes}, payload

    def list_audit(self, actor: GroupActor, space_id: str, *, limit: int) -> list[dict]:
        with self.database.session() as db:
            self._require_membership(db, space_id, actor, roles={"owner", "admin"})
            items = db.scalars(select(GroupAuditEvent).where(GroupAuditEvent.space_id == space_id).order_by(GroupAuditEvent.created_at.desc(), GroupAuditEvent.id.desc()).limit(limit)).all()
            result = []
            for item in items:
                try:
                    metadata = json.loads(item.metadata_json)
                except json.JSONDecodeError:
                    metadata = {}
                result.append({"id": item.id, "event_type": item.event_type, "resource_type": item.resource_type, "resource_id": item.resource_id, "actor": {"type": item.actor_type, "id": item.actor_id, "user_id": item.actor_user_id}, "outcome": item.outcome, "metadata": metadata, "created_at": _iso(item.created_at)})
            return result
