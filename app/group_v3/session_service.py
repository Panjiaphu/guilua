from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.core.config import Settings
from app.db import Database
from app.group_v3.auth import GroupActor
from app.group_v3.media import (
    GroupMediaProviderError,
    LiveKitGroupMediaProvider,
    participant_identity,
    room_name,
)
from app.group_v3.service import GroupServiceError
from app.models import (
    GroupAuditEvent,
    GroupMediaParticipant,
    GroupMediaSession,
    GroupMembership,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


class GroupMediaSessionService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        provider: LiveKitGroupMediaProvider,
        event_broker=None,
    ):
        self.database = database
        self.settings = settings
        self.provider = provider
        self.event_broker = event_broker

    def _enqueue(self, db, space_id: str, event_type: str, resource_id: object = "") -> None:
        if self.event_broker:
            self.event_broker.enqueue_in_transaction(db, space_id, event_type, resource_id=resource_id)

    @staticmethod
    def _membership(db, space_id: str, actor: GroupActor) -> GroupMembership:
        item = db.scalar(
            select(GroupMembership).where(
                GroupMembership.space_id == space_id,
                GroupMembership.principal_type == actor.principal_type,
                GroupMembership.principal_id == actor.principal_id,
                GroupMembership.principal_user_id == actor.principal_user_id,
                GroupMembership.status == "active",
            )
        )
        if not item:
            raise GroupServiceError("group_membership_required", 403)
        return item

    @staticmethod
    def _participant(db, session_id: str, actor: GroupActor, *, for_update: bool = False) -> GroupMediaParticipant:
        query = select(GroupMediaParticipant).where(
            GroupMediaParticipant.session_id == session_id,
            GroupMediaParticipant.principal_type == actor.principal_type,
            GroupMediaParticipant.principal_id == actor.principal_id,
            GroupMediaParticipant.principal_user_id == actor.principal_user_id,
        )
        if for_update:
            query = query.with_for_update()
        item = db.scalar(query)
        if not item:
            raise GroupServiceError("group_media_participant_required", 403)
        return item

    @staticmethod
    def _audit(
        db,
        actor: GroupActor,
        space_id: str,
        event_type: str,
        session_id: str,
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
                resource_type="media_session",
                resource_id=session_id,
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            )
        )

    @staticmethod
    def _participant_payload(item: GroupMediaParticipant) -> dict:
        return {
            "id": item.id,
            "membership_id": item.membership_id,
            "display_name": item.display_name,
            "livekit_identity": item.livekit_identity,
            "invite_status": item.invite_status,
            "connection_status": item.connection_status,
            "connection_error_code": item.connection_error_code,
            "joined_at": _iso(item.joined_at),
            "rejected_at": _iso(item.rejected_at),
            "left_at": _iso(item.left_at),
        }

    def _session_payload(self, db, session: GroupMediaSession) -> dict:
        participants = list(
            db.scalars(
                select(GroupMediaParticipant)
                .where(GroupMediaParticipant.session_id == session.id)
                .order_by(GroupMediaParticipant.invited_at, GroupMediaParticipant.id)
            ).all()
        )
        return {
            "id": session.id,
            "space_id": session.space_id,
            "media_kind": session.media_kind,
            "title": session.title,
            "initiated_by_membership_id": session.initiated_by_membership_id,
            "status": session.status,
            "version": session.version,
            "participants": [self._participant_payload(item) for item in participants],
            "started_at": _iso(session.started_at),
            "ended_at": _iso(session.ended_at),
            "end_reason": session.end_reason,
            "created_at": _iso(session.created_at),
            "updated_at": _iso(session.updated_at),
        }

    @staticmethod
    def _locked_session(db, space_id: str, session_id: str) -> GroupMediaSession:
        session = db.scalar(
            select(GroupMediaSession)
            .where(GroupMediaSession.id == session_id, GroupMediaSession.space_id == space_id)
            .with_for_update()
        )
        if not session:
            raise GroupServiceError("group_media_session_not_found", 404)
        return session

    def create_session(self, actor: GroupActor, space_id: str, values: dict) -> dict:
        if not self.settings.group_media_enabled:
            raise GroupServiceError("group_media_disabled", 503)
        requested = values["participant_membership_ids"]
        if len(requested) + 1 > self.settings.group_media_max_participants:
            raise GroupServiceError("group_media_capacity_exceeded", 409)
        session_id = str(uuid4())
        with self.database.session() as db:
            with db.begin():
                actor_membership = self._membership(db, space_id, actor)
                if actor_membership.id in requested:
                    raise GroupServiceError("group_media_self_invite", 400)
                invitees = list(
                    db.scalars(
                        select(GroupMembership).where(
                            GroupMembership.space_id == space_id,
                            GroupMembership.id.in_(requested),
                            GroupMembership.status == "active",
                        )
                    ).all()
                )
                if len(invitees) != len(requested):
                    raise GroupServiceError("group_media_invitee_not_found", 404)
                session = GroupMediaSession(
                    id=session_id,
                    space_id=space_id,
                    media_kind=values["media_kind"],
                    title=values.get("title") or "",
                    initiated_by_membership_id=actor_membership.id,
                    livekit_room_name=room_name(session_id),
                    status="ringing",
                )
                participants = [actor_membership, *invitees]
                db.add(session)
                db.flush()
                for membership in participants:
                    is_actor = membership.id == actor_membership.id
                    db.add(
                        GroupMediaParticipant(
                            id=str(uuid4()),
                            session_id=session.id,
                            membership_id=membership.id,
                            principal_type=membership.principal_type,
                            principal_id=membership.principal_id,
                            principal_user_id=membership.principal_user_id,
                            display_name=membership.display_name,
                            livekit_identity=participant_identity(session.id, membership.id),
                            invite_status="joined" if is_actor else "invited",
                            connection_status="not_connected",
                            joined_at=_now() if is_actor else None,
                        )
                    )
                self._audit(db, actor, space_id, "media_session.ringing", session.id, {"media_kind": session.media_kind, "invitee_count": len(invitees)})
                db.flush()
                db.refresh(session)
                self._enqueue(db, space_id, "media_session.created", session.id)
                return self._session_payload(db, session)

    def list_sessions(self, actor: GroupActor, space_id: str, status: str | None, limit: int) -> list[dict]:
        with self.database.session() as db:
            membership = self._membership(db, space_id, actor)
            query = (
                select(GroupMediaSession)
                .join(GroupMediaParticipant, GroupMediaParticipant.session_id == GroupMediaSession.id)
                .where(
                    GroupMediaSession.space_id == space_id,
                    GroupMediaParticipant.membership_id == membership.id,
                )
            )
            if status:
                query = query.where(GroupMediaSession.status == status)
            sessions = list(db.scalars(query.order_by(GroupMediaSession.created_at.desc()).limit(limit)).all())
            return [self._session_payload(db, item) for item in sessions]

    def get_session(self, actor: GroupActor, space_id: str, session_id: str) -> dict:
        with self.database.session() as db:
            self._membership(db, space_id, actor)
            session = db.get(GroupMediaSession, session_id)
            if not session or session.space_id != space_id:
                raise GroupServiceError("group_media_session_not_found", 404)
            self._participant(db, session_id, actor)
            return self._session_payload(db, session)

    def join(self, actor: GroupActor, space_id: str, session_id: str) -> dict:
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                session = self._locked_session(db, space_id, session_id)
                participant = self._participant(db, session_id, actor, for_update=True)
                if session.status == "ended":
                    raise GroupServiceError("group_media_session_ended", 409)
                if participant.invite_status in {"rejected", "left"}:
                    raise GroupServiceError("group_media_participant_terminal", 409)
                if participant.invite_status == "invited":
                    participant.invite_status = "joined"
                    participant.joined_at = _now()
                    participant.updated_at = _now()
                    # Join is idempotent. A duplicate/retried Join must not
                    # regress an already connecting or connected participant.
                    participant.connection_status = "not_connected"
                    participant.connection_error_code = ""
                self._audit(db, actor, space_id, "media_session.joined", session.id)
                self._enqueue(db, space_id, "media_session.joined", session.id)
                db.flush()
                return self._session_payload(db, session)

    def update_connection_state(
        self,
        actor: GroupActor,
        space_id: str,
        session_id: str,
        status: str,
        failure_code: str = "",
    ) -> dict:
        if status not in {"connecting", "connected", "reconnecting", "failed"}:
            raise GroupServiceError("invalid_media_connection_status", 400)
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                session = self._locked_session(db, space_id, session_id)
                participant = self._participant(db, session_id, actor, for_update=True)
                if session.status == "ended":
                    raise GroupServiceError("group_media_session_ended", 409)
                if participant.invite_status != "joined":
                    raise GroupServiceError("group_media_join_required", 409)
                participant.connection_status = status
                participant.connection_error_code = str(failure_code or "")[:80] if status == "failed" else ""
                participant.updated_at = _now()
                if status == "connected" and session.status == "ringing":
                    session.status = "active"
                    session.started_at = _now()
                    session.version += 1
                    session.updated_at = _now()
                self._audit(
                    db,
                    actor,
                    space_id,
                    "media_session.connection_state",
                    session.id,
                    {"status": status, "failure_code": participant.connection_error_code},
                )
                self._enqueue(db, space_id, "media_session.connection_state", session.id)
                db.flush()
                return self._session_payload(db, session)

    def reject(self, actor: GroupActor, space_id: str, session_id: str) -> dict:
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                session = self._locked_session(db, space_id, session_id)
                participant = self._participant(db, session_id, actor, for_update=True)
                if session.status == "ended":
                    raise GroupServiceError("group_media_session_ended", 409)
                if participant.invite_status != "invited":
                    raise GroupServiceError("group_media_reject_not_allowed", 409)
                participant.invite_status = "rejected"
                participant.rejected_at = _now()
                participant.updated_at = _now()
                remaining_invites = db.scalar(
                    select(GroupMediaParticipant.id).where(
                        GroupMediaParticipant.session_id == session.id,
                        GroupMediaParticipant.invite_status == "invited",
                        GroupMediaParticipant.id != participant.id,
                    ).limit(1)
                )
                if not remaining_invites and session.status == "ringing":
                    session.status = "ended"
                    session.ended_at = _now()
                    session.end_reason = "all_invites_rejected"
                    session.version += 1
                self._audit(db, actor, space_id, "media_session.rejected", session.id)
                self._enqueue(db, space_id, "media_session.rejected", session.id)
                db.flush()
                return self._session_payload(db, session)

    def leave(self, actor: GroupActor, space_id: str, session_id: str) -> dict:
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                session = self._locked_session(db, space_id, session_id)
                participant = self._participant(db, session_id, actor, for_update=True)
                if session.status == "ended":
                    return self._session_payload(db, session)
                if participant.invite_status != "joined":
                    raise GroupServiceError("group_media_leave_not_allowed", 409)
                participant.invite_status = "left"
                participant.left_at = _now()
                participant.updated_at = _now()
                another_joined = db.scalar(
                    select(GroupMediaParticipant.id).where(
                        GroupMediaParticipant.session_id == session.id,
                        GroupMediaParticipant.invite_status == "joined",
                        GroupMediaParticipant.id != participant.id,
                    ).limit(1)
                )
                if not another_joined:
                    session.status = "ended"
                    session.ended_at = _now()
                    session.ended_by_membership_id = participant.membership_id
                    session.end_reason = "last_participant_left"
                    session.version += 1
                self._audit(db, actor, space_id, "media_session.left", session.id, {"ended_for_all": False})
                self._enqueue(db, space_id, "media_session.left", session.id)
                db.flush()
                return self._session_payload(db, session)

    def end_for_all(self, actor: GroupActor, space_id: str, session_id: str) -> dict:
        with self.database.session() as db:
            with db.begin():
                actor_membership = self._membership(db, space_id, actor)
                session = self._locked_session(db, space_id, session_id)
                if actor_membership.id != session.initiated_by_membership_id and actor_membership.role not in {"owner", "admin"}:
                    raise GroupServiceError("group_media_end_for_all_denied", 403)
                if session.status != "ended":
                    now = _now()
                    participants = list(db.scalars(select(GroupMediaParticipant).where(GroupMediaParticipant.session_id == session.id)).all())
                    for participant in participants:
                        if participant.invite_status == "joined":
                            participant.invite_status = "left"
                            participant.left_at = now
                        elif participant.invite_status == "invited":
                            participant.invite_status = "rejected"
                            participant.rejected_at = now
                        participant.updated_at = now
                    session.status = "ended"
                    session.ended_at = now
                    session.ended_by_membership_id = actor_membership.id
                    session.end_reason = "ended_for_all"
                    session.version += 1
                    session.updated_at = now
                    self._audit(db, actor, space_id, "media_session.ended_for_all", session.id, {"ended_for_all": True})
                    self._enqueue(db, space_id, "media_session.ended_for_all", session.id)
                db.flush()
                return self._session_payload(db, session)

    def update_video_subscriptions(
        self,
        actor: GroupActor,
        space_id: str,
        session_id: str,
        membership_ids: list[str],
    ) -> dict:
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                session = self._locked_session(db, space_id, session_id)
                participant = self._participant(db, session_id, actor, for_update=True)
                if session.media_kind != "video" or session.status != "active" or participant.invite_status != "joined":
                    raise GroupServiceError("group_video_subscriptions_not_available", 409)
                targets = list(
                    db.scalars(
                        select(GroupMediaParticipant).where(
                            GroupMediaParticipant.session_id == session.id,
                            GroupMediaParticipant.membership_id.in_(membership_ids),
                            GroupMediaParticipant.invite_status == "joined",
                        )
                    ).all()
                ) if membership_ids else []
                if len(targets) != len(membership_ids) or any(item.id == participant.id for item in targets):
                    raise GroupServiceError("group_video_subscription_target_invalid", 409)
                identities = tuple(item.livekit_identity for item in targets)
                participant.desired_video_subscriptions_json = json.dumps(identities, separators=(",", ":"))
                participant.updated_at = _now()
                self._audit(db, actor, space_id, "media_session.video_subscriptions_updated", session.id, {"target_count": len(identities)})
                self._enqueue(db, space_id, "media_session.video_subscriptions_updated", session.id)
                return {"session_id": session.id, "desired_video_subscriptions": list(identities)}

    def media_grant(self, actor: GroupActor, space_id: str, session_id: str) -> dict:
        with self.database.session() as db:
            self._membership(db, space_id, actor)
            session = db.get(GroupMediaSession, session_id)
            if not session or session.space_id != space_id:
                raise GroupServiceError("group_media_session_not_found", 404)
            participant = self._participant(db, session_id, actor)
            if session.status not in {"ringing", "active"} or participant.invite_status != "joined":
                # RINGING still has no grant until this participant explicitly joins.
                raise GroupServiceError("group_media_grant_not_ready", 409)
            try:
                desired = tuple(json.loads(participant.desired_video_subscriptions_json))
            except (json.JSONDecodeError, TypeError):
                desired = ()
            room = session.livekit_room_name
            identity = participant.livekit_identity
            media_kind = session.media_kind
        try:
            grant = self.provider.issue_grant(
                room=room,
                identity=identity,
                media_kind=media_kind,
                desired_video_subscriptions=desired,
            )
        except GroupMediaProviderError as exc:
            raise GroupServiceError(exc.code, exc.status_code) from exc
        return {
            "provider": grant.provider,
            "url": grant.url,
            "room": grant.room,
            "participant_identity": grant.participant_identity,
            "token": grant.token,
            "expires_at": grant.expires_at,
            "media_kind": grant.media_kind,
            "desired_video_subscriptions": list(grant.desired_video_subscriptions),
        }
