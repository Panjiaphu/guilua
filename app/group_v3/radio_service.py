from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db import Database
from app.group_v3.auth import GroupActor
from app.group_v3.media import GroupMediaProviderError, LiveKitGroupMediaProvider, participant_identity, room_name
from app.group_v3.service import GroupServiceError
from app.models import (
    GroupAuditEvent,
    GroupLanguageProfile,
    GroupMembership,
    GroupRadioBurst,
    GroupRadioParticipant,
    GroupRadioProcessingJob,
    GroupRadioSession,
    GroupSpace,
    GroupTranslationConsent,
    GroupTranslationSegment,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class GroupRadioService:
    def __init__(self, database: Database, settings: Settings, provider: LiveKitGroupMediaProvider, event_broker=None):
        self.database = database
        self.settings = settings
        self.provider = provider
        self.event_broker = event_broker

    def _enqueue(self, db, space_id: str, event_type: str, resource_id: object = "") -> None:
        if self.event_broker:
            self.event_broker.enqueue_in_transaction(db, space_id, event_type, resource_id=resource_id)

    def _enabled(self) -> None:
        if not self.settings.group_radio_v3_enabled:
            raise GroupServiceError("group_radio_v3_disabled", 503)

    @staticmethod
    def _membership(db, space_id: str, actor: GroupActor) -> GroupMembership:
        item = db.scalar(select(GroupMembership).where(GroupMembership.space_id == space_id, GroupMembership.principal_type == actor.principal_type, GroupMembership.principal_id == actor.principal_id, GroupMembership.principal_user_id == actor.principal_user_id, GroupMembership.status == "active"))
        if not item:
            raise GroupServiceError("group_membership_required", 403)
        return item

    @staticmethod
    def _participant(db, radio_session_id: str, actor: GroupActor, *, joined: bool = False, for_update: bool = False) -> GroupRadioParticipant:
        query = select(GroupRadioParticipant).where(GroupRadioParticipant.radio_session_id == radio_session_id, GroupRadioParticipant.principal_type == actor.principal_type, GroupRadioParticipant.principal_id == actor.principal_id, GroupRadioParticipant.principal_user_id == actor.principal_user_id)
        if joined:
            query = query.where(GroupRadioParticipant.status == "joined")
        if for_update:
            query = query.with_for_update()
        item = db.scalar(query)
        if not item:
            raise GroupServiceError("group_radio_participant_required", 403)
        return item

    @staticmethod
    def _session(db, space_id: str, session_id: str, *, for_update: bool = False) -> GroupRadioSession:
        query = select(GroupRadioSession).where(GroupRadioSession.id == session_id, GroupRadioSession.space_id == space_id)
        if for_update:
            query = query.with_for_update()
        item = db.scalar(query)
        if not item:
            raise GroupServiceError("group_radio_session_not_found", 404)
        return item

    @staticmethod
    def _audit(db, actor: GroupActor, space_id: str, event_type: str, resource_type: str, resource_id: str, metadata: dict | None = None) -> None:
        db.add(GroupAuditEvent(id=str(uuid4()), space_id=space_id, actor_type=actor.principal_type, actor_id=actor.principal_id, actor_user_id=actor.principal_user_id, event_type=event_type, resource_type=resource_type, resource_id=resource_id, metadata_json=json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))

    @staticmethod
    def _participant_payload(item: GroupRadioParticipant) -> dict:
        return {"id": item.id, "membership_id": item.membership_id, "display_name": item.display_name, "livekit_identity": item.livekit_identity, "status": item.status, "device_state": item.device_state, "joined_at": _iso(item.joined_at), "left_at": _iso(item.left_at), "device_lost_at": _iso(item.device_lost_at)}

    def _session_payload(self, db, session: GroupRadioSession) -> dict:
        participants = list(db.scalars(select(GroupRadioParticipant).where(GroupRadioParticipant.radio_session_id == session.id).order_by(GroupRadioParticipant.created_at, GroupRadioParticipant.id)).all())
        return {"id": session.id, "space_id": session.space_id, "title": session.title, "status": session.status, "version": session.version, "participants": [self._participant_payload(item) for item in participants], "ended_at": _iso(session.ended_at), "created_at": _iso(session.created_at), "updated_at": _iso(session.updated_at)}

    @staticmethod
    def _burst_payload(item: GroupRadioBurst) -> dict:
        try:
            targets = json.loads(item.target_languages_json)
        except json.JSONDecodeError:
            targets = []
        return {"id": item.id, "radio_session_id": item.radio_session_id, "speaker_membership_id": item.speaker_membership_id, "state": item.state, "source_language": item.source_language, "target_languages": targets, "stop_reason": item.stop_reason, "started_at": _iso(item.started_at), "stopped_at": _iso(item.stopped_at), "finalized_at": _iso(item.finalized_at)}

    def create_session(self, actor: GroupActor, space_id: str, values: dict) -> dict:
        self._enabled()
        requested = values["participant_membership_ids"]
        if len(requested) + 1 > self.settings.group_media_max_participants:
            raise GroupServiceError("group_radio_capacity_exceeded", 409)
        session_id = str(uuid4())
        with self.database.session() as db:
            try:
                with db.begin():
                    creator = self._membership(db, space_id, actor)
                    if creator.id in requested:
                        raise GroupServiceError("group_radio_self_invite", 400)
                    invitees = list(db.scalars(select(GroupMembership).where(GroupMembership.space_id == space_id, GroupMembership.id.in_(requested), GroupMembership.status == "active")).all())
                    if len(invitees) != len(requested):
                        raise GroupServiceError("group_radio_invitee_not_found", 404)
                    session = GroupRadioSession(id=session_id, space_id=space_id, title=values.get("title") or "", created_by_membership_id=creator.id, livekit_room_name=room_name(f"radio:{session_id}"), status="ready")
                    db.add(session)
                    # Radio participants reference the newly-created session.
                    # Materialize the parent before inserting dependents when
                    # SQLite FK enforcement or PostgreSQL is in use.
                    db.flush()
                    for membership in [creator, *invitees]:
                        is_creator = membership.id == creator.id
                        db.add(GroupRadioParticipant(id=str(uuid4()), radio_session_id=session.id, membership_id=membership.id, principal_type=membership.principal_type, principal_id=membership.principal_id, principal_user_id=membership.principal_user_id, display_name=membership.display_name, livekit_identity=participant_identity(f"radio:{session.id}", membership.id), status="joined" if is_creator else "invited", joined_at=_now() if is_creator else None))
                    self._audit(db, actor, space_id, "radio.session_created", "radio_session", session.id, {"invitee_count": len(invitees)})
                    db.flush()
                    db.refresh(session)
                    self._enqueue(db, space_id, "radio.session_created", session.id)
                    return self._session_payload(db, session)
            except IntegrityError as exc:
                raise GroupServiceError("group_radio_session_conflict", 409) from exc

    def list_sessions(self, actor: GroupActor, space_id: str, status: str | None, limit: int) -> list[dict]:
        self._enabled()
        with self.database.session() as db:
            membership = self._membership(db, space_id, actor)
            query = select(GroupRadioSession).join(GroupRadioParticipant, GroupRadioParticipant.radio_session_id == GroupRadioSession.id).where(GroupRadioSession.space_id == space_id, GroupRadioParticipant.membership_id == membership.id)
            if status:
                query = query.where(GroupRadioSession.status == status)
            sessions = list(db.scalars(query.order_by(GroupRadioSession.created_at.desc()).limit(limit)).all())
            return [self._session_payload(db, item) for item in sessions]

    def get_session(self, actor: GroupActor, space_id: str, session_id: str) -> dict:
        self._enabled()
        with self.database.session() as db:
            self._membership(db, space_id, actor)
            session = self._session(db, space_id, session_id)
            self._participant(db, session.id, actor)
            return self._session_payload(db, session)

    def open_room(self, actor, space_id):
        """One current transport epoch per persistent space-level Radio room."""
        self._enabled()
        with self.database.session() as db:
            with db.begin():
                member = self._membership(db, space_id, actor)
                db.scalar(select(GroupSpace).where(GroupSpace.id == space_id).with_for_update())
                session = db.scalar(select(GroupRadioSession).where(
                    GroupRadioSession.space_id == space_id, GroupRadioSession.status == "ready"
                ).order_by(GroupRadioSession.created_at.desc()).limit(1))
                if not session:
                    session_id = str(uuid4())
                    session = GroupRadioSession(id=session_id, space_id=space_id,
                        title="", created_by_membership_id=member.id,
                        livekit_room_name=room_name(f"radio:{session_id}"), status="ready")
                    db.add(session)
                    db.flush()
                    self._enqueue(db, space_id, "radio.session_created", session_id)
                session_id = session.id
        return self.join(actor, space_id, session_id)

    def join(self, actor: GroupActor, space_id: str, session_id: str) -> dict:
        self._enabled()
        with self.database.session() as db:
            with db.begin():
                member = self._membership(db, space_id, actor)
                session = self._session(db, space_id, session_id, for_update=True)
                participant = db.scalar(select(GroupRadioParticipant).where(
                    GroupRadioParticipant.radio_session_id == session.id,
                    GroupRadioParticipant.membership_id == member.id,
                ).with_for_update())
                if session.status != "ready":
                    raise GroupServiceError("group_radio_join_not_allowed", 409)
                joined = list(db.scalars(select(GroupRadioParticipant.id).where(
                    GroupRadioParticipant.radio_session_id == session.id, GroupRadioParticipant.status == "joined"
                )).all())
                if (not participant or participant.status != "joined") and len(joined) >= self.settings.group_media_max_participants:
                    raise GroupServiceError("group_radio_capacity_exceeded", 409)
                if not participant:
                    participant = GroupRadioParticipant(id=str(uuid4()), radio_session_id=session.id,
                        membership_id=member.id, principal_type=member.principal_type,
                        principal_id=member.principal_id, principal_user_id=member.principal_user_id,
                        display_name=member.display_name,
                        livekit_identity=participant_identity(f"radio:{session.id}", member.id))
                    db.add(participant)
                participant.status = "joined"
                participant.device_state = "ready"
                participant.joined_at = participant.joined_at or _now()
                participant.left_at = None
                participant.updated_at = _now()
                self._audit(db, actor, space_id, "radio.participant_joined", "radio_session", session.id)
                self._enqueue(db, space_id, "radio.participant_joined", session.id)
                db.flush()
                return self._session_payload(db, session)

    def reject(self, actor: GroupActor, space_id: str, session_id: str) -> dict:
        self._enabled()
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                session = self._session(db, space_id, session_id, for_update=True)
                participant = self._participant(db, session.id, actor, for_update=True)
                if session.status != "ready" or participant.status != "invited":
                    raise GroupServiceError("group_radio_reject_not_allowed", 409)
                participant.status = "left"
                participant.left_at = _now()
                participant.updated_at = _now()
                self._audit(
                    db,
                    actor,
                    space_id,
                    "radio.participant_rejected",
                    "radio_session",
                    session.id,
                )
                self._enqueue(db, space_id, "radio.participant_rejected", session.id)
                db.flush()
                return self._session_payload(db, session)

    def leave(self, actor: GroupActor, space_id: str, session_id: str) -> dict:
        self._enabled()
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                session = self._session(db, space_id, session_id, for_update=True)
                participant = self._participant(db, session.id, actor, for_update=True)
                if participant.status == "left":
                    return self._session_payload(db, session)
                # Defensive closure after the caller released this member's floor.
                for burst in db.scalars(select(GroupRadioBurst).where(
                    GroupRadioBurst.radio_session_id == session.id,
                    GroupRadioBurst.speaker_membership_id == participant.membership_id,
                    GroupRadioBurst.state == "talking",
                ).with_for_update()).all():
                    burst.state = "failed"
                    burst.stop_reason = "left_without_clip"
                    burst.stopped_at = burst.finalized_at = _now()
                participant.status = "left"
                participant.left_at = _now()
                participant.updated_at = _now()
                self._audit(db, actor, space_id, "radio.participant_left", "radio_session", session.id, {"ended_for_all": False})
                self._enqueue(db, space_id, "radio.participant_left", session.id)
                db.flush()
                return self._session_payload(db, session)

    def end_for_all(self, actor: GroupActor, space_id: str, session_id: str) -> dict:
        self._enabled()
        with self.database.session() as db:
            with db.begin():
                membership = self._membership(db, space_id, actor)
                session = self._session(db, space_id, session_id, for_update=True)
                if membership.id != session.created_by_membership_id and membership.role not in {"owner", "admin"}:
                    raise GroupServiceError("group_radio_end_for_all_denied", 403)
                if session.status != "ended":
                    now = _now()
                    session.status = "ended"
                    session.ended_by_membership_id = membership.id
                    session.ended_at = now
                    session.updated_at = now
                    session.version += 1
                    for participant in db.scalars(select(GroupRadioParticipant).where(GroupRadioParticipant.radio_session_id == session.id)).all():
                        if participant.status == "joined":
                            participant.status = "left"
                            participant.left_at = now
                    self._audit(db, actor, space_id, "radio.session_ended_for_all", "radio_session", session.id, {"ended_for_all": True})
                    self._enqueue(db, space_id, "radio.session_ended_for_all", session.id)
                db.flush()
                return self._session_payload(db, session)

    def floor_context(self, actor: GroupActor, space_id: str, session_id: str) -> tuple[dict, dict]:
        self._enabled()
        with self.database.session() as db:
            self._membership(db, space_id, actor)
            session = self._session(db, space_id, session_id)
            participant = self._participant(db, session.id, actor, joined=True)
            if session.status != "ready" or participant.device_state != "ready":
                raise GroupServiceError("group_radio_floor_not_available", 409)
            return self._session_payload(db, session), self._participant_payload(participant)

    def record_burst(self, actor: GroupActor, space_id: str, session_id: str, floor_token: str, source_language: str, target_languages: list[str]) -> dict:
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                session = self._session(db, space_id, session_id, for_update=True)
                participant = self._participant(db, session.id, actor, joined=True, for_update=True)
                if session.status != "ready" or participant.device_state != "ready":
                    raise GroupServiceError("group_radio_floor_not_available", 409)
                active = db.scalar(select(GroupRadioBurst).where(GroupRadioBurst.radio_session_id == session.id, GroupRadioBurst.state == "talking").with_for_update())
                if active:
                    raise GroupServiceError("group_radio_burst_conflict", 409)
                planned_targets: list[str] = []
                if self.settings.group_translation_enabled:
                    joined_membership_ids = list(
                        db.scalars(
                            select(GroupRadioParticipant.membership_id).where(
                                GroupRadioParticipant.radio_session_id == session.id,
                                GroupRadioParticipant.status == "joined",
                            )
                        ).all()
                    )
                    consented = set(
                        db.scalars(
                            select(GroupTranslationConsent.membership_id).where(
                                GroupTranslationConsent.space_id == space_id,
                                GroupTranslationConsent.membership_id.in_(joined_membership_ids),
                                GroupTranslationConsent.status == "granted",
                                GroupTranslationConsent.policy_version
                                == self.settings.group_translation_policy_version,
                            )
                        ).all()
                    )
                    if len(consented) == len(set(joined_membership_ids)):
                        preferred = db.scalars(
                            select(GroupLanguageProfile.preferred_output_language).where(
                                GroupLanguageProfile.space_id == space_id,
                                GroupLanguageProfile.membership_id.in_(joined_membership_ids),
                            )
                        ).all()
                        planned_targets = sorted(
                            {item for item in preferred if item != source_language}
                        )[: self.settings.group_translation_max_targets]
                burst = GroupRadioBurst(id=str(uuid4()), radio_session_id=session.id, space_id=space_id, speaker_participant_id=participant.id, speaker_membership_id=participant.membership_id, floor_token_hash=_token_hash(floor_token), state="talking", source_language=source_language, target_languages_json=json.dumps(planned_targets, separators=(",", ":")), started_at=_now())
                db.add(burst)
                self._audit(db, actor, space_id, "radio.floor_acquired", "radio_burst", burst.id, {"target_language_count": len(planned_targets), "targets_from_recipient_profiles": True})
                self._enqueue(db, space_id, "radio.floor_acquired", burst.id)
                db.flush()
                return self._burst_payload(burst)

    def burst_for_token(self, actor: GroupActor, space_id: str, session_id: str, floor_token: str) -> dict:
        with self.database.session() as db:
            self._membership(db, space_id, actor)
            session = self._session(db, space_id, session_id)
            participant = self._participant(db, session.id, actor)
            burst = db.scalar(select(GroupRadioBurst).where(GroupRadioBurst.radio_session_id == session.id, GroupRadioBurst.speaker_participant_id == participant.id, GroupRadioBurst.floor_token_hash == _token_hash(floor_token)).order_by(GroupRadioBurst.created_at.desc()).limit(1))
            if not burst:
                raise GroupServiceError("group_radio_burst_not_found", 404)
            return self._burst_payload(burst)

    def stop_burst_after_floor_release(self, actor: GroupActor, space_id: str, session_id: str, floor_token: str, reason: str = "stop") -> dict:
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                session = self._session(db, space_id, session_id)
                participant = self._participant(db, session.id, actor)
                burst = db.scalar(select(GroupRadioBurst).where(GroupRadioBurst.radio_session_id == session.id, GroupRadioBurst.speaker_participant_id == participant.id, GroupRadioBurst.floor_token_hash == _token_hash(floor_token)).order_by(GroupRadioBurst.created_at.desc()).with_for_update())
                if not burst:
                    raise GroupServiceError("group_radio_burst_not_found", 404)
                if burst.state == "talking":
                    try:
                        targets = json.loads(burst.target_languages_json)
                    except json.JSONDecodeError:
                        targets = []
                    # Source transcription is required even for same-language rooms.
                    processing = self.settings.group_translation_enabled
                    burst.state = "finalizing" if processing else "final"
                    burst.stop_reason = reason[:40]
                    burst.stopped_at = _now()
                    burst.finalized_at = None if processing else burst.stopped_at
                    burst.updated_at = _now()
                    db.add(GroupRadioProcessingJob(id=str(uuid4()), burst_id=burst.id, status="ready" if processing else "completed"))
                    self._audit(db, actor, space_id, "radio.burst_floor_released", "radio_burst", burst.id, {"before_downstream": True, "reason": reason[:40]})
                    self._enqueue(db, space_id, "radio.floor_released", burst.id)
                db.flush()
                return self._burst_payload(burst)

    def device_lost_after_floor_release(self, actor: GroupActor, space_id: str, session_id: str, floor_token: str) -> dict:
        with self.database.session() as db:
            with db.begin():
                self._membership(db, space_id, actor)
                session = self._session(db, space_id, session_id)
                participant = self._participant(db, session.id, actor, for_update=True)
                burst = db.scalar(select(GroupRadioBurst).where(GroupRadioBurst.radio_session_id == session.id, GroupRadioBurst.speaker_participant_id == participant.id, GroupRadioBurst.floor_token_hash == _token_hash(floor_token)).order_by(GroupRadioBurst.created_at.desc()).with_for_update())
                if not burst:
                    raise GroupServiceError("group_radio_burst_not_found", 404)
                if burst.state == "talking":
                    now = _now()
                    burst.state = "device_lost"
                    burst.stop_reason = "device_lost"
                    burst.stopped_at = now
                    burst.finalized_at = now
                    burst.updated_at = now
                    participant.device_state = "lost"
                    participant.device_lost_at = now
                    participant.updated_at = now
                    db.add(GroupRadioProcessingJob(id=str(uuid4()), burst_id=burst.id, status="suppressed", failure_code="device_lost_private_audio_suppressed"))
                    self._audit(db, actor, space_id, "radio.burst_device_lost", "radio_burst", burst.id, {"private_audio_playback": "suppressed"})
                    self._enqueue(db, space_id, "radio.device_lost", burst.id)
                db.flush()
                return self._burst_payload(burst)

    def issue_media_grant(self, actor: GroupActor, space_id: str, session_id: str, *, can_publish: bool) -> dict:
        with self.database.session() as db:
            self._membership(db, space_id, actor)
            session = self._session(db, space_id, session_id)
            participant = self._participant(db, session.id, actor, joined=True)
            if session.status != "ready" or participant.device_state != "ready":
                raise GroupServiceError("group_radio_media_not_available", 409)
            room = session.livekit_room_name
            identity = participant.livekit_identity
        try:
            grant = self.provider.issue_grant(room=room, identity=identity, media_kind="audio", desired_video_subscriptions=(), can_publish=can_publish)
        except GroupMediaProviderError as exc:
            raise GroupServiceError(exc.code, exc.status_code) from exc
        return {"provider": grant.provider, "url": grant.url, "room": grant.room, "participant_identity": grant.participant_identity, "token": grant.token, "expires_at": grant.expires_at, "media_kind": "audio", "publish_mode": "talk" if can_publish else "listen"}

    def history(self, actor: GroupActor, space_id: str, session_id: str, limit: int) -> list[dict]:
        with self.database.session() as db:
            self._membership(db, space_id, actor)
            session = self._session(db, space_id, session_id)
            self._participant(db, session.id, actor)
            bursts = list(db.scalars(select(GroupRadioBurst).where(GroupRadioBurst.radio_session_id == session.id).order_by(GroupRadioBurst.created_at.desc()).limit(limit)).all())
            return [self._burst_payload(item) for item in bursts]

    def leave_context(self, actor, space_id, session_id):
        # Exit authorization is intentionally independent of device/floor state.
        with self.database.session() as db:
            member = self._membership(db, space_id, actor)
            self._session(db, space_id, session_id)
            self._participant(db, session_id, actor)
            return member.id

    def room_history(self, actor, space_id, translation_service, limit=50, before_id=None):
        with self.database.session() as db:
            self._membership(db, space_id, actor)
            query = select(GroupRadioBurst).where(
                GroupRadioBurst.space_id == space_id,
            )
            if before_id:
                cursor = db.get(GroupRadioBurst, before_id)
                if not cursor or cursor.space_id != space_id:
                    raise GroupServiceError("invalid_history_cursor", 400)
                cursor_time = select(GroupRadioBurst.started_at).where(GroupRadioBurst.id == cursor.id).scalar_subquery()
                query = query.where(or_(GroupRadioBurst.started_at < cursor_time,
                    and_(GroupRadioBurst.started_at == cursor_time, GroupRadioBurst.id < cursor.id)))
            rows = db.scalars(query.order_by(GroupRadioBurst.started_at.desc(), GroupRadioBurst.id.desc())
                              .limit(max(1, min(limit, 100)))).all()
            result = []
            for burst in rows:
                item = self._burst_payload(burst)
                speaker = db.get(GroupMembership, burst.speaker_membership_id)
                item["speaker_display_name"] = speaker.display_name
                segment = db.scalar(select(GroupTranslationSegment).where(
                    GroupTranslationSegment.space_id == space_id,
                    GroupTranslationSegment.runtime_kind == "radio",
                    GroupTranslationSegment.runtime_id == burst.radio_session_id,
                    GroupTranslationSegment.speaker_membership_id == burst.speaker_membership_id,
                    GroupTranslationSegment.client_segment_id == burst.id,
                ))
                item["segment"] = translation_service._project_v2(db, actor, segment) if segment else None
                job = db.scalar(select(GroupRadioProcessingJob).where(GroupRadioProcessingJob.burst_id == burst.id))
                item["failure_code"] = job.failure_code if job else ""
                # A lost upload/process never leaves an unexplained eternal spinner.
                if not segment and job and job.status in {"ready", "processing"}:
                    updated = job.updated_at.replace(tzinfo=timezone.utc) if job.updated_at.tzinfo is None else job.updated_at
                    if _now() - updated > timedelta(minutes=5):
                        item["state"], item["failure_code"] = "failed", "group_radio_transcription_interrupted"
                result.append(item)
            return result

    async def reconcile_device_loss(self, floor) -> int:
        if not self.settings.group_radio_v3_enabled:
            return 0
        cutoff = _now() - timedelta(seconds=self.settings.group_radio_device_lost_seconds)
        with self.database.session() as db:
            candidates = [
                (item.id, item.radio_session_id, item.speaker_participant_id)
                for item in db.scalars(
                    select(GroupRadioBurst).where(
                        GroupRadioBurst.state == "talking",
                        GroupRadioBurst.started_at <= cutoff,
                    )
                ).all()
            ]
        lost: list[tuple[str, str]] = []
        for burst_id, session_id, participant_id in candidates:
            snapshot = await floor.snapshot(session_id)
            if not snapshot or snapshot.get("participant_id") != participant_id:
                lost.append((burst_id, participant_id))
        count = 0
        for burst_id, participant_id in lost:
            with self.database.session() as db:
                with db.begin():
                    burst = db.scalar(select(GroupRadioBurst).where(GroupRadioBurst.id == burst_id).with_for_update())
                    if not burst or burst.state != "talking":
                        continue
                    participant = db.get(GroupRadioParticipant, participant_id)
                    membership = db.get(GroupMembership, burst.speaker_membership_id)
                    now = _now()
                    burst.state = "device_lost"
                    burst.stop_reason = "heartbeat_lost"
                    burst.stopped_at = now
                    burst.finalized_at = now
                    burst.updated_at = now
                    if participant:
                        participant.device_state = "lost"
                        participant.device_lost_at = now
                        participant.updated_at = now
                    db.add(GroupRadioProcessingJob(id=str(uuid4()), burst_id=burst.id, status="suppressed", failure_code="device_lost_private_audio_suppressed"))
                    if membership:
                        db.add(GroupAuditEvent(id=str(uuid4()), space_id=burst.space_id, actor_type=membership.principal_type, actor_id=membership.principal_id, actor_user_id=membership.principal_user_id, event_type="radio.burst_device_lost", resource_type="radio_burst", resource_id=burst.id, metadata_json='{"private_audio_playback":"suppressed","source":"heartbeat"}'))
                    count += 1
        return count
