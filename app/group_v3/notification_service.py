from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.db import Database
from app.group_v3.auth import GroupActor
from app.group_v3.notification_presence import GroupNotificationPresence
from app.group_v3.service import GroupServiceError
from app.integrations.timeblock.client import TimeblockIntegrationError
from app.models import (
    GroupEventOutbox,
    GroupInvitation,
    GroupMediaParticipant,
    GroupMediaSession,
    GroupMembership,
    GroupMessage,
    GroupNotificationDelivery,
    GroupRadioParticipant,
    GroupRadioSession,
    GroupSpace,
)


logger = logging.getLogger(__name__)

_ALL_CHAT_COALESCE_SECONDS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _future(value: datetime | None, now: datetime) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value > now


class GroupNotificationService:
    """Metadata-only Group policy engine and cross-system delivery worker."""

    def __init__(
        self,
        database: Database,
        timeblock_client: Any,
        presence: GroupNotificationPresence,
    ) -> None:
        self.database = database
        self.timeblock_client = timeblock_client
        self.presence = presence
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    @staticmethod
    def _membership(db, actor: GroupActor, space_id: str, *, lock: bool = False) -> GroupMembership:
        query = select(GroupMembership).where(
            GroupMembership.space_id == space_id,
            GroupMembership.principal_type == actor.principal_type,
            GroupMembership.principal_id == actor.principal_id,
            GroupMembership.principal_user_id == actor.principal_user_id,
            GroupMembership.status == "active",
        )
        if lock:
            query = query.with_for_update()
        membership = db.scalar(query)
        if not membership:
            raise GroupServiceError("group_membership_required", 403)
        return membership

    @staticmethod
    def _preference_payload(item: GroupMembership) -> dict[str, Any]:
        muted_until = item.notification_muted_until
        if muted_until and not _future(muted_until, _now()):
            muted_until = None
        return {
            "mode": item.notification_mode,
            "muted_until": _iso(muted_until),
            "paused": bool(item.notification_paused),
            "last_seen_sequence": item.last_seen_sequence,
            "unread_count": item.unread_count,
        }

    def preferences(self, actor: GroupActor, space_id: str) -> dict[str, Any]:
        with self.database.session() as db:
            return self._preference_payload(self._membership(db, actor, space_id))

    def update_preferences(
        self,
        actor: GroupActor,
        space_id: str,
        mode: str,
        mute_for_minutes: int | None,
    ) -> dict[str, Any]:
        with self.database.session() as db:
            with db.begin():
                membership = self._membership(db, actor, space_id, lock=True)
                membership.notification_mode = mode
                if mute_for_minutes is not None:
                    if mute_for_minutes == -1:
                        membership.notification_paused = 1
                        membership.notification_muted_until = None
                    elif mute_for_minutes == 0:
                        membership.notification_paused = 0
                        membership.notification_muted_until = None
                    else:
                        membership.notification_paused = 0
                        membership.notification_muted_until = _now() + timedelta(
                            minutes=mute_for_minutes
                        )
                membership.updated_at = _now()
                return self._preference_payload(membership)

    def membership_id(self, actor: GroupActor, space_id: str) -> str:
        with self.database.session() as db:
            return self._membership(db, actor, space_id).id

    def mark_read(
        self, actor: GroupActor, space_id: str, requested_sequence: int
    ) -> dict[str, Any]:
        with self.database.session() as db:
            with db.begin():
                membership = self._membership(db, actor, space_id, lock=True)
                space = db.get(GroupSpace, space_id)
                if not space or space.lifecycle_status != "active":
                    raise GroupServiceError("group_space_not_found", 404)
                sequence = min(max(requested_sequence, membership.last_seen_sequence), space.message_sequence)
                membership.last_seen_sequence = sequence
                membership.unread_count = int(
                    db.scalar(
                        select(func.count(GroupMessage.id)).where(
                            GroupMessage.space_id == space_id,
                            GroupMessage.status == "active",
                            GroupMessage.sequence > sequence,
                            or_(
                                GroupMessage.sender_type != actor.principal_type,
                                GroupMessage.sender_id != actor.principal_id,
                                GroupMessage.sender_user_id != actor.principal_user_id,
                            ),
                        )
                    )
                    or 0
                )
                membership.updated_at = _now()
                db.execute(
                    update(GroupNotificationDelivery)
                    .where(
                        GroupNotificationDelivery.recipient_membership_id == membership.id,
                        GroupNotificationDelivery.event_kind.in_(
                            ("group.chat.activity", "group.chat.reply", "group.chat.mention")
                        ),
                        GroupNotificationDelivery.status.in_(("pending", "processing", "failed")),
                    )
                    .values(
                        status="suppressed",
                        last_error="group_space_read",
                        updated_at=_now(),
                    )
                )
                return self._preference_payload(membership)

    @staticmethod
    def _is_muted(item: GroupMembership, now: datetime) -> bool:
        return bool(item.notification_paused) or _future(item.notification_muted_until, now)

    @staticmethod
    def _recipient_matches_message(item: GroupMembership, message: GroupMessage) -> bool:
        return (
            item.principal_type == message.sender_type
            and item.principal_id == message.sender_id
            and item.principal_user_id == message.sender_user_id
        )

    @staticmethod
    def _metadata(**values: Any) -> str:
        return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _add_delivery(
        self,
        db,
        event: GroupEventOutbox,
        *,
        membership: GroupMembership | None,
        recipient_type: str,
        recipient_id: str,
        recipient_user_id: str,
        notification_class: str,
        event_kind: str,
        resource_id: str,
        push_eligible: bool,
        metadata_json: str,
        expires_at: datetime | None = None,
    ) -> None:
        exists = db.scalar(
            select(GroupNotificationDelivery.id).where(
                GroupNotificationDelivery.group_event_id == event.id,
                GroupNotificationDelivery.recipient_type == recipient_type,
                GroupNotificationDelivery.recipient_id == recipient_id,
                GroupNotificationDelivery.recipient_user_id == recipient_user_id,
                GroupNotificationDelivery.notification_class == notification_class,
            )
        )
        if exists:
            return
        db.add(
            GroupNotificationDelivery(
                id=str(uuid4()),
                group_event_id=event.id,
                space_id=event.space_id,
                resource_id=resource_id[:80],
                recipient_membership_id=membership.id if membership else None,
                recipient_type=recipient_type,
                recipient_id=recipient_id,
                recipient_user_id=recipient_user_id,
                notification_class=notification_class,
                event_kind=event_kind,
                push_eligible=int(push_eligible),
                metadata_json=metadata_json,
                status="pending",
                next_attempt_at=_now(),
                expires_at=expires_at,
            )
        )

    @staticmethod
    def _recent_chat_activity_exists(
        db,
        *,
        recipient_membership_id: str,
        space_id: str,
        now: datetime,
    ) -> bool:
        """Bound ``all`` mode bursts without changing unread accounting.

        A delivery that can still reach (or already reached) Timeblock owns the
        short aggregation window. A suppressed delivery does not, so leaving an
        actively viewed space cannot hide the next eligible notification.
        """

        return bool(
            db.scalar(
                select(GroupNotificationDelivery.id).where(
                    GroupNotificationDelivery.recipient_membership_id
                    == recipient_membership_id,
                    GroupNotificationDelivery.space_id == space_id,
                    GroupNotificationDelivery.notification_class == "chat-activity",
                    GroupNotificationDelivery.status.in_(
                        ("pending", "processing", "failed", "delivered")
                    ),
                    GroupNotificationDelivery.created_at
                    >= now - timedelta(seconds=_ALL_CHAT_COALESCE_SECONDS),
                ).limit(1)
            )
        )

    def _expand_chat(self, db, event: GroupEventOutbox) -> None:
        message = db.get(GroupMessage, event.resource_id)
        space = db.get(GroupSpace, event.space_id)
        if not message or not space or message.status != "active":
            return
        reply = db.get(GroupMessage, message.reply_to_id) if message.reply_to_id else None
        recipients = list(
            db.scalars(
                select(GroupMembership)
                .where(
                    GroupMembership.space_id == event.space_id,
                    GroupMembership.status == "active",
                )
                .order_by(GroupMembership.id)
                .with_for_update()
            ).all()
        )
        now = _now()
        for recipient in recipients:
            if self._recipient_matches_message(recipient, message):
                continue
            if message.sequence <= recipient.last_seen_sequence:
                continue
            first_unread = recipient.unread_count == 0
            recipient.unread_count += 1
            recipient.updated_at = now
            if self._is_muted(recipient, now) or recipient.notification_mode == "none":
                continue
            is_reply = bool(reply and self._recipient_matches_message(recipient, reply))
            if is_reply:
                notification_class = "chat-reply"
                event_kind = "group.chat.reply"
                push_eligible = True
            elif recipient.notification_mode == "all":
                if self._recent_chat_activity_exists(
                    db,
                    recipient_membership_id=recipient.id,
                    space_id=event.space_id,
                    now=now,
                ):
                    continue
                notification_class = "chat-activity"
                event_kind = "group.chat.activity"
                push_eligible = True
            elif recipient.notification_mode == "smart" and first_unread:
                notification_class = "chat-activity"
                event_kind = "group.chat.activity"
                push_eligible = False
            else:
                # Important mode has no normal-message path. Structured
                # mentions remain intentionally deferred until canonical IDs
                # exist; display-name regex is forbidden.
                continue
            self._add_delivery(
                db,
                event,
                membership=recipient,
                recipient_type=recipient.principal_type,
                recipient_id=recipient.principal_id,
                recipient_user_id=recipient.principal_user_id,
                notification_class=notification_class,
                event_kind=event_kind,
                resource_id=message.id,
                push_eligible=push_eligible,
                metadata_json=self._metadata(
                    space_title=space.title,
                    sender_type=message.sender_type,
                    sender_id=message.sender_id,
                    sender_user_id=message.sender_user_id,
                    sender_display_name=message.sender_display_name,
                    surface="chat",
                    message_id=message.id,
                    sequence=message.sequence,
                    created_at=_iso(message.created_at),
                ),
            )

    def _expand_invitation(self, db, event: GroupEventOutbox) -> None:
        invitation = db.get(GroupInvitation, event.resource_id)
        space = db.get(GroupSpace, event.space_id)
        if not invitation or not space or invitation.status != "pending":
            return
        inviter = db.get(GroupMembership, invitation.invited_by_membership_id)
        self._add_delivery(
            db,
            event,
            membership=None,
            recipient_type=invitation.target_type,
            recipient_id=invitation.target_id,
            recipient_user_id="",
            notification_class="group-invitation",
            event_kind="group.invitation",
            resource_id=invitation.id,
            push_eligible=True,
            expires_at=invitation.expires_at,
            metadata_json=self._metadata(
                space_title=space.title,
                initiator_type=inviter.principal_type if inviter else "",
                initiator_id=inviter.principal_id if inviter else "",
                initiator_display_name=inviter.display_name if inviter else "",
                surface="chat",
                invitation_id=invitation.id,
                created_at=_iso(invitation.created_at),
            ),
        )

    def _expand_media(self, db, event: GroupEventOutbox) -> None:
        session = db.get(GroupMediaSession, event.resource_id)
        space = db.get(GroupSpace, event.space_id)
        if not session or not space or session.status != "ringing":
            return
        initiator = db.get(GroupMembership, session.initiated_by_membership_id)
        participants = list(
            db.scalars(
                select(GroupMediaParticipant).where(
                    GroupMediaParticipant.session_id == session.id,
                    GroupMediaParticipant.invite_status == "invited",
                )
            ).all()
        )
        now = _now()
        event_kind = (
            "group.video.incoming" if session.media_kind == "video" else "group.call.incoming"
        )
        surface = "video" if session.media_kind == "video" else "call"
        for participant in participants:
            membership = db.scalar(
                select(GroupMembership)
                .where(
                    GroupMembership.id == participant.membership_id,
                    GroupMembership.status == "active",
                )
                .with_for_update()
            )
            if not membership or self._is_muted(membership, now) or membership.notification_mode == "none":
                continue
            self._add_delivery(
                db,
                event,
                membership=membership,
                recipient_type=membership.principal_type,
                recipient_id=membership.principal_id,
                recipient_user_id=membership.principal_user_id,
                notification_class=f"{surface}-incoming",
                event_kind=event_kind,
                resource_id=session.id,
                push_eligible=True,
                expires_at=now + timedelta(seconds=90),
                metadata_json=self._metadata(
                    space_title=space.title,
                    initiator_type=initiator.principal_type if initiator else "",
                    initiator_id=initiator.principal_id if initiator else "",
                    initiator_user_id=initiator.principal_user_id if initiator else "",
                    initiator_display_name=initiator.display_name if initiator else "",
                    surface=surface,
                    session_id=session.id,
                    created_at=_iso(session.created_at),
                ),
            )

    def _expand_media_missed(self, db, event: GroupEventOutbox) -> None:
        session = db.get(GroupMediaSession, event.resource_id)
        space = db.get(GroupSpace, event.space_id)
        if not session or not space or session.status != "ended" or not session.ended_at:
            return
        if event.event_type not in {"media_session.left", "media_session.ended_for_all"}:
            return
        initiator = db.get(GroupMembership, session.initiated_by_membership_id)
        participants = list(
            db.scalars(
                select(GroupMediaParticipant).where(
                    GroupMediaParticipant.session_id == session.id,
                    GroupMediaParticipant.membership_id
                    != session.initiated_by_membership_id,
                )
            ).all()
        )
        now = _now()
        surface = "video" if session.media_kind == "video" else "call"
        event_kind = f"group.{surface}.missed"
        for participant in participants:
            unanswered = participant.invite_status == "invited"
            if event.event_type == "media_session.ended_for_all":
                # end_for_all atomically marks invitations rejected. Matching
                # timestamps distinguish unanswered invitees from users who
                # explicitly rejected earlier in the session.
                unanswered = bool(
                    participant.invite_status == "rejected"
                    and participant.joined_at is None
                    and participant.rejected_at == session.ended_at
                )
            if not unanswered:
                continue
            membership = db.scalar(
                select(GroupMembership)
                .where(
                    GroupMembership.id == participant.membership_id,
                    GroupMembership.status == "active",
                )
                .with_for_update()
            )
            if (
                not membership
                or self._is_muted(membership, now)
                or membership.notification_mode == "none"
            ):
                continue
            self._add_delivery(
                db,
                event,
                membership=membership,
                recipient_type=membership.principal_type,
                recipient_id=membership.principal_id,
                recipient_user_id=membership.principal_user_id,
                notification_class=f"{surface}-missed",
                event_kind=event_kind,
                resource_id=session.id,
                push_eligible=True,
                metadata_json=self._metadata(
                    space_title=space.title,
                    initiator_type=initiator.principal_type if initiator else "",
                    initiator_id=initiator.principal_id if initiator else "",
                    initiator_user_id=(
                        initiator.principal_user_id if initiator else ""
                    ),
                    initiator_display_name=initiator.display_name if initiator else "",
                    surface=surface,
                    session_id=session.id,
                    created_at=_iso(session.ended_at),
                ),
            )

    def _expand_radio(self, db, event: GroupEventOutbox) -> None:
        session = db.get(GroupRadioSession, event.resource_id)
        space = db.get(GroupSpace, event.space_id)
        if not session or not space or session.status not in {"ready", "active"}:
            return
        initiator = db.get(GroupMembership, session.created_by_membership_id)
        participants = list(
            db.scalars(
                select(GroupRadioParticipant).where(
                    GroupRadioParticipant.radio_session_id == session.id,
                    GroupRadioParticipant.status == "invited",
                )
            ).all()
        )
        now = _now()
        for participant in participants:
            membership = db.scalar(
                select(GroupMembership)
                .where(
                    GroupMembership.id == participant.membership_id,
                    GroupMembership.status == "active",
                )
                .with_for_update()
            )
            if not membership or self._is_muted(membership, now) or membership.notification_mode == "none":
                continue
            self._add_delivery(
                db,
                event,
                membership=membership,
                recipient_type=membership.principal_type,
                recipient_id=membership.principal_id,
                recipient_user_id=membership.principal_user_id,
                notification_class="radio-invited",
                event_kind="group.radio.invited",
                resource_id=session.id,
                push_eligible=True,
                metadata_json=self._metadata(
                    space_title=space.title,
                    initiator_type=initiator.principal_type if initiator else "",
                    initiator_id=initiator.principal_id if initiator else "",
                    initiator_user_id=initiator.principal_user_id if initiator else "",
                    initiator_display_name=initiator.display_name if initiator else "",
                    surface="radio",
                    session_id=session.id,
                    created_at=_iso(session.created_at),
                ),
            )

    def _claim_event(self) -> str | None:
        now = _now()
        with self.database.session() as db:
            with db.begin():
                event = db.scalar(
                    select(GroupEventOutbox)
                    .where(
                        GroupEventOutbox.notification_status.in_(
                            ("pending", "failed", "processing")
                        ),
                        GroupEventOutbox.notification_next_attempt_at <= now,
                    )
                    .order_by(GroupEventOutbox.created_at, GroupEventOutbox.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if not event:
                    return None
                event.notification_status = "processing"
                event.notification_attempts += 1
                event.notification_next_attempt_at = now + timedelta(seconds=30)
                event.notification_last_error = ""
                return event.id

    def _expand_claimed(self, event_id: str) -> None:
        try:
            with self.database.session() as db:
                with db.begin():
                    event = db.scalar(
                        select(GroupEventOutbox)
                        .where(GroupEventOutbox.id == event_id)
                        .with_for_update()
                    )
                    if not event or event.notification_status != "processing":
                        return
                    if event.event_type == "message.created":
                        self._expand_chat(db, event)
                    elif event.event_type == "invitation.created":
                        self._expand_invitation(db, event)
                    elif event.event_type == "media_session.created":
                        self._expand_media(db, event)
                    elif event.event_type in {
                        "media_session.left",
                        "media_session.ended_for_all",
                    }:
                        self._expand_media_missed(db, event)
                    elif event.event_type == "radio.session_created":
                        self._expand_radio(db, event)
                    event.notification_status = "completed"
                    event.notification_dispatched_at = _now()
                    event.notification_last_error = ""
        except Exception as exc:
            logger.exception("Group notification expansion failed for %s", event_id)
            with self.database.session() as db:
                with db.begin():
                    event = db.get(GroupEventOutbox, event_id)
                    if event:
                        event.notification_status = "failed"
                        event.notification_last_error = str(exc)[:160]
                        event.notification_next_attempt_at = _now() + timedelta(
                            seconds=min(300, 2 ** min(event.notification_attempts, 8))
                        )

    def _claim_delivery(self) -> dict[str, Any] | None:
        now = _now()
        with self.database.session() as db:
            with db.begin():
                row = db.scalar(
                    select(GroupNotificationDelivery)
                    .where(
                        GroupNotificationDelivery.status.in_(
                            ("pending", "failed", "processing")
                        ),
                        GroupNotificationDelivery.next_attempt_at <= now,
                    )
                    .order_by(GroupNotificationDelivery.created_at, GroupNotificationDelivery.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if not row:
                    return None
                row.status = "processing"
                row.attempts += 1
                row.next_attempt_at = now + timedelta(seconds=30)
                row.last_error = ""
                return {
                    "id": row.id,
                    "group_event_id": row.group_event_id,
                    "space_id": row.space_id,
                    "resource_id": row.resource_id,
                    "recipient_membership_id": row.recipient_membership_id,
                    "recipient_type": row.recipient_type,
                    "recipient_id": row.recipient_id,
                    "recipient_user_id": row.recipient_user_id,
                    "notification_class": row.notification_class,
                    "event_kind": row.event_kind,
                    "push_eligible": bool(row.push_eligible),
                    "metadata_json": row.metadata_json,
                    "expires_at": row.expires_at,
                    "attempts": row.attempts,
                }

    def _delivery_current(self, claimed: dict[str, Any]) -> tuple[bool, str]:
        now = _now()
        expires_at = claimed["expires_at"]
        if expires_at and not _future(expires_at, now):
            return False, "notification_expired"
        with self.database.session() as db:
            membership_id = claimed["recipient_membership_id"]
            if membership_id:
                membership = db.get(GroupMembership, membership_id)
                if not membership or membership.status != "active":
                    return False, "recipient_membership_inactive"
                if self._is_muted(membership, now) or membership.notification_mode == "none":
                    return False, "group_notifications_disabled"
                if claimed["event_kind"].startswith("group.chat.") and membership.unread_count <= 0:
                    return False, "group_space_already_read"
            elif claimed["event_kind"] == "group.invitation":
                invitation = db.get(GroupInvitation, claimed["resource_id"])
                if not invitation or invitation.status != "pending":
                    return False, "group_invitation_not_pending"

            if claimed["event_kind"] in {"group.call.incoming", "group.video.incoming"}:
                session = db.get(GroupMediaSession, claimed["resource_id"])
                participant = db.scalar(
                    select(GroupMediaParticipant).where(
                        GroupMediaParticipant.session_id == claimed["resource_id"],
                        GroupMediaParticipant.membership_id == membership_id,
                    )
                )
                if not session or session.status != "ringing" or not participant or participant.invite_status != "invited":
                    return False, "group_media_session_not_ringing"
            elif claimed["event_kind"] in {"group.radio.invited", "group.radio.started"}:
                session = db.get(GroupRadioSession, claimed["resource_id"])
                participant = db.scalar(
                    select(GroupRadioParticipant).where(
                        GroupRadioParticipant.radio_session_id == claimed["resource_id"],
                        GroupRadioParticipant.membership_id == membership_id,
                    )
                )
                if not session or session.status not in {"ready", "active"} or not participant or participant.status != "invited":
                    return False, "group_radio_session_not_invited"
        return True, ""

    def _mark_delivery(self, delivery_id: str, status: str, error: str = "") -> None:
        with self.database.session() as db:
            with db.begin():
                row = db.get(GroupNotificationDelivery, delivery_id)
                if not row:
                    return
                row.status = status
                row.last_error = error[:160]
                row.updated_at = _now()
                if status == "delivered":
                    row.delivered_at = row.updated_at
                elif status == "failed":
                    row.next_attempt_at = row.updated_at + timedelta(
                        seconds=min(300, 2 ** min(row.attempts, 8))
                    )

    async def _deliver_claimed(self, claimed: dict[str, Any]) -> None:
        current, reason = self._delivery_current(claimed)
        if not current:
            self._mark_delivery(claimed["id"], "suppressed", reason)
            return
        membership_id = claimed["recipient_membership_id"]
        if membership_id:
            active = await self.presence.is_active(claimed["space_id"], membership_id)
            if active is True:
                self._mark_delivery(claimed["id"], "suppressed", "same_space_visible")
                return
        try:
            metadata = json.loads(claimed["metadata_json"] or "{}")
            if not isinstance(metadata, dict):
                raise ValueError("group_notification_metadata_invalid")
            result = await self.timeblock_client.ingest_group_notification(
                {
                    "group_event_id": claimed["group_event_id"],
                    "recipient": {
                        "type": claimed["recipient_type"],
                        "id": claimed["recipient_id"],
                        "user_id": claimed["recipient_user_id"],
                    },
                    "notification_class": claimed["notification_class"],
                    "event_kind": claimed["event_kind"],
                    "space_id": claimed["space_id"],
                    "resource_id": claimed["resource_id"],
                    "push_eligible": claimed["push_eligible"],
                    "metadata": metadata,
                },
                idempotency_key=(
                    f"group:{claimed['group_event_id']}:{claimed['recipient_type']}:"
                    f"{claimed['recipient_id']}:{claimed['recipient_user_id']}:"
                    f"{claimed['notification_class']}"
                )[:256],
            )
            receipt = result.get("receipt") if isinstance(result, dict) else None
            push_state = (
                str(receipt.get("push_state") or "")
                if isinstance(receipt, dict)
                else ""
            )
            if push_state in {"claimed", "failed"}:
                raise TimeblockIntegrationError(
                    "timeblock_group_notification_pending"
                )
        except (TimeblockIntegrationError, ValueError) as exc:
            self._mark_delivery(claimed["id"], "failed", str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive transport boundary
            logger.exception("Unexpected Timeblock Group notification failure")
            self._mark_delivery(claimed["id"], "failed", str(exc))
            return
        self._mark_delivery(claimed["id"], "delivered")

    async def drain(self, limit: int = 100) -> dict[str, int]:
        expanded = delivered = 0
        try:
            for _ in range(max(1, min(int(limit), 500))):
                event_id = self._claim_event()
                if not event_id:
                    break
                self._expand_claimed(event_id)
                expanded += 1
            for _ in range(max(1, min(int(limit), 500))):
                claimed = self._claim_delivery()
                if not claimed:
                    break
                await self._deliver_claimed(claimed)
                delivered += 1
        except (OperationalError, ProgrammingError) as exc:
            # During a pre-deploy migration window the old process may not yet
            # have 0024. Readiness remains fail-closed; Group business writes
            # are never converted into notification failures.
            logger.warning("Group notification schema unavailable; retrying later: %s", exc)
        return {"expanded": expanded, "processed": delivered}

    def kick(self) -> None:
        if self._closed or (self._task and not self._task.done()):
            return

        async def runner() -> None:
            try:
                await self.drain()
            except Exception:  # pragma: no cover - defensive background boundary
                logger.exception("Group notification worker failed")

        self._task = asyncio.create_task(runner())

    async def close(self) -> None:
        self._closed = True
        if self._task:
            if not self._task.done():
                self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.presence.close()
