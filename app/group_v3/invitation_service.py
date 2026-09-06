from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db import Database
from app.group_v3.auth import GroupActor
from app.group_v3.service import GroupService, GroupServiceError, _canonical_json, _iso
from app.models import GroupAuditEvent, GroupInvitation, GroupMembership, GroupSpace


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GroupInvitationService:
    def __init__(self, database: Database, invitation_ttl_seconds: int, event_broker=None):
        self.database = database
        self.invitation_ttl_seconds = invitation_ttl_seconds
        self.event_broker = event_broker

    def _enqueue(self, db, space_id: str, event_type: str, resource_id: object = "") -> None:
        if self.event_broker:
            self.event_broker.enqueue_in_transaction(
                db, space_id, event_type, resource_id=resource_id
            )

    @staticmethod
    def _require_membership(db, actor: GroupActor, space_id: str, roles: set[str] | None = None):
        membership = GroupService._membership(db, space_id, actor)
        if not membership:
            raise GroupServiceError("group_membership_required", 403)
        if roles and membership.role not in roles:
            raise GroupServiceError("group_permission_denied", 403)
        return membership

    def require_manager(self, actor: GroupActor, space_id: str) -> None:
        with self.database.session() as db:
            self._require_membership(db, actor, space_id, {"owner", "admin"})

    @staticmethod
    def _expire_pending(db) -> None:
        db.execute(
            update(GroupInvitation)
            .where(
                GroupInvitation.status == "pending",
                GroupInvitation.expires_at <= _now(),
            )
            .values(status="expired", pending_key=None, updated_at=_now())
        )

    @staticmethod
    def _payload(item: GroupInvitation, *, space_title: str = "") -> dict[str, Any]:
        return {
            "id": item.id,
            "space_id": item.space_id,
            "contact_ref": item.target_public_id,
            "principal_type": item.target_type,
            "display_name": item.target_display_name,
            "role": item.role,
            "status": item.status,
            "expires_at": _iso(item.expires_at),
            "created_at": _iso(item.created_at),
            "space_title": space_title[:120],
        }

    @staticmethod
    def _audit(db, actor: GroupActor, space_id: str, event_type: str, invitation_id: str) -> None:
        db.add(
            GroupAuditEvent(
                id=str(uuid4()),
                space_id=space_id,
                actor_type=actor.principal_type,
                actor_id=actor.principal_id,
                actor_user_id=actor.principal_user_id,
                event_type=event_type,
                resource_type="invitation",
                resource_id=invitation_id,
                metadata_json=_canonical_json({}),
            )
        )

    @staticmethod
    def connection_candidates(payload: dict[str, Any]) -> list[dict[str, str]]:
        rows: Any = payload.get("connections")
        if not isinstance(rows, list):
            rows = payload.get("items")
        if not isinstance(rows, list):
            rows = payload.get("friendships")
        if not isinstance(rows, list):
            rows = []
        candidates: dict[str, dict[str, str]] = {}
        for row in rows:
            if not isinstance(row, dict) or str(row.get("status") or "") != "accepted":
                continue
            if str(row.get("block_state") or "none") != "none":
                continue
            peer = row.get("peer")
            if not isinstance(peer, dict) or str(peer.get("status") or "active") != "active":
                continue
            principal_type = str(peer.get("owner_type") or peer.get("type") or "").strip()
            principal_id = str(peer.get("owner_id") or peer.get("id") or "").strip()
            public_id = str(peer.get("public_id") or "").strip()
            display_name = str(peer.get("display_name") or "").strip()
            if (
                principal_type not in {"member", "business"}
                or not principal_id
                or not public_id
                or not display_name
            ):
                continue
            candidates[public_id] = {
                "contact_ref": public_id[:128],
                "principal_type": principal_type,
                "principal_id": principal_id[:128],
                "display_name": display_name[:120],
                "handle": str(peer.get("handle") or "")[:120],
                "avatar_url": str(peer.get("avatar_url") or "")[:500],
            }
        return list(candidates.values())

    def list_candidates(
        self,
        actor: GroupActor,
        space_id: str,
        directory_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        candidates = self.connection_candidates(directory_payload)
        with self.database.session() as db:
            with db.begin():
                self._require_membership(db, actor, space_id, {"owner", "admin"})
                self._expire_pending(db)
                memberships = {
                    (item.principal_type, item.principal_id)
                    for item in db.scalars(
                        select(GroupMembership).where(
                            GroupMembership.space_id == space_id,
                            GroupMembership.status == "active",
                        )
                    ).all()
                }
                invitations = {
                    (item.target_type, item.target_id)
                    for item in db.scalars(
                        select(GroupInvitation).where(
                            GroupInvitation.space_id == space_id,
                            GroupInvitation.status == "pending",
                        )
                    ).all()
                }
                return [
                    {
                        "contact_ref": item["contact_ref"],
                        "principal_type": item["principal_type"],
                        "display_name": item["display_name"],
                        "handle": item["handle"],
                        "avatar_url": item["avatar_url"],
                        "membership_status": "active"
                        if (item["principal_type"], item["principal_id"]) in memberships
                        else "invited"
                        if (item["principal_type"], item["principal_id"]) in invitations
                        else "available",
                    }
                    for item in candidates
                    if (item["principal_type"], item["principal_id"])
                    != (actor.principal_type, actor.principal_id)
                ]

    def create_invitation(
        self,
        actor: GroupActor,
        space_id: str,
        contact_ref: str,
        directory_payload: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = next(
            (item for item in self.connection_candidates(directory_payload) if item["contact_ref"] == contact_ref),
            None,
        )
        if not candidate:
            raise GroupServiceError("group_invitation_contact_not_available", 404)
        if (candidate["principal_type"], candidate["principal_id"]) == (
            actor.principal_type,
            actor.principal_id,
        ):
            raise GroupServiceError("group_invitation_self_not_allowed", 409)
        pending_key = f"{space_id}:{candidate['principal_type']}:{candidate['principal_id']}"
        try:
            with self.database.session() as db:
                with db.begin():
                    inviter = self._require_membership(db, actor, space_id, {"owner", "admin"})
                    self._expire_pending(db)
                    existing_member = db.scalar(
                        select(GroupMembership).where(
                            GroupMembership.space_id == space_id,
                            GroupMembership.principal_type == candidate["principal_type"],
                            GroupMembership.principal_id == candidate["principal_id"],
                            GroupMembership.status == "active",
                        )
                    )
                    if existing_member:
                        raise GroupServiceError("group_membership_exists", 409)
                    existing = db.scalar(
                        select(GroupInvitation).where(GroupInvitation.pending_key == pending_key)
                    )
                    if existing:
                        return {"invitation": self._payload(existing), "idempotent": True}
                    item = GroupInvitation(
                        id=str(uuid4()),
                        space_id=space_id,
                        target_type=candidate["principal_type"],
                        target_id=candidate["principal_id"],
                        target_public_id=candidate["contact_ref"],
                        target_display_name=candidate["display_name"],
                        invited_by_membership_id=inviter.id,
                        role="member",
                        status="pending",
                        pending_key=pending_key,
                        expires_at=_now() + timedelta(seconds=self.invitation_ttl_seconds),
                    )
                    db.add(item)
                    db.flush()
                    self._audit(db, actor, space_id, "invitation.created", item.id)
                    self._enqueue(db, space_id, "invitation.created", item.id)
                    return {"invitation": self._payload(item), "idempotent": False}
        except IntegrityError as exc:
            with self.database.session() as db:
                existing = db.scalar(
                    select(GroupInvitation).where(
                        GroupInvitation.pending_key == pending_key,
                        GroupInvitation.status == "pending",
                    )
                )
                if existing:
                    return {"invitation": self._payload(existing), "idempotent": True}
            raise GroupServiceError("group_invitation_conflict", 409) from exc

    def list_space_invitations(self, actor: GroupActor, space_id: str) -> list[dict[str, Any]]:
        with self.database.session() as db:
            with db.begin():
                self._require_membership(db, actor, space_id, {"owner", "admin"})
                self._expire_pending(db)
                rows = db.scalars(
                    select(GroupInvitation)
                    .where(GroupInvitation.space_id == space_id)
                    .order_by(GroupInvitation.created_at.desc(), GroupInvitation.id)
                ).all()
                return [self._payload(item) for item in rows]

    def list_incoming(self, actor: GroupActor) -> list[dict[str, Any]]:
        with self.database.session() as db:
            with db.begin():
                self._expire_pending(db)
                rows = db.execute(
                    select(GroupInvitation, GroupSpace.title)
                    .join(GroupSpace, GroupSpace.id == GroupInvitation.space_id)
                    .where(
                        GroupInvitation.target_type == actor.principal_type,
                        GroupInvitation.target_id == actor.principal_id,
                        GroupInvitation.status == "pending",
                    )
                    .order_by(GroupInvitation.created_at.desc(), GroupInvitation.id)
                ).all()
                return [self._payload(item, space_title=space_title) for item, space_title in rows]

    def cancel(self, actor: GroupActor, space_id: str, invitation_id: str) -> dict[str, Any]:
        with self.database.session() as db:
            with db.begin():
                self._require_membership(db, actor, space_id, {"owner", "admin"})
                self._expire_pending(db)
                item = db.get(GroupInvitation, invitation_id)
                if not item or item.space_id != space_id:
                    raise GroupServiceError("group_invitation_not_found", 404)
                if item.status == "cancelled":
                    return self._payload(item)
                if item.status != "pending":
                    raise GroupServiceError("group_invitation_not_pending", 409)
                item.status = "cancelled"
                item.pending_key = None
                item.cancelled_at = _now()
                item.updated_at = _now()
                self._audit(db, actor, space_id, "invitation.cancelled", item.id)
                self._enqueue(db, space_id, "invitation.cancelled", item.id)
                return self._payload(item)

    def decide(self, actor: GroupActor, invitation_id: str, *, accept: bool) -> dict[str, Any]:
        with self.database.session() as db:
            try:
                with db.begin():
                    self._expire_pending(db)
                    item = db.scalar(
                        select(GroupInvitation)
                        .where(GroupInvitation.id == invitation_id)
                        .with_for_update()
                    )
                    if not item or item.target_type != actor.principal_type or item.target_id != actor.principal_id:
                        raise GroupServiceError("group_invitation_not_found", 404)
                    if item.status == "accepted" and item.accepted_by_user_id == actor.principal_user_id:
                        membership = db.scalar(
                            select(GroupMembership).where(
                                GroupMembership.space_id == item.space_id,
                                GroupMembership.principal_type == actor.principal_type,
                                GroupMembership.principal_id == actor.principal_id,
                                GroupMembership.principal_user_id == actor.principal_user_id,
                            )
                        )
                        return {
                            "invitation": self._payload(item),
                            "membership": GroupService._membership_payload(membership) if membership else None,
                            "idempotent": True,
                        }
                    if item.status != "pending":
                        raise GroupServiceError("group_invitation_not_pending", 409)
                    item.pending_key = None
                    item.updated_at = _now()
                    if not accept:
                        item.status = "rejected"
                        item.rejected_at = _now()
                        self._audit(db, actor, item.space_id, "invitation.rejected", item.id)
                        self._enqueue(db, item.space_id, "invitation.rejected", item.id)
                        return {"invitation": self._payload(item), "membership": None, "idempotent": False}
                    membership = db.scalar(
                        select(GroupMembership).where(
                            GroupMembership.space_id == item.space_id,
                            GroupMembership.principal_type == actor.principal_type,
                            GroupMembership.principal_id == actor.principal_id,
                            GroupMembership.principal_user_id == actor.principal_user_id,
                        )
                    )
                    if membership:
                        membership.display_name = actor.display_name
                        membership.role = "member"
                        membership.status = "active"
                        membership.left_at = None
                        membership.updated_at = _now()
                    else:
                        membership = GroupMembership(
                            id=str(uuid4()),
                            space_id=item.space_id,
                            principal_type=actor.principal_type,
                            principal_id=actor.principal_id,
                            principal_user_id=actor.principal_user_id,
                            display_name=actor.display_name,
                            role="member",
                            status="active",
                        )
                        db.add(membership)
                    item.status = "accepted"
                    item.accepted_by_user_id = actor.principal_user_id
                    item.accepted_at = _now()
                    db.flush()
                    self._audit(db, actor, item.space_id, "invitation.accepted", item.id)
                    self._enqueue(db, item.space_id, "invitation.accepted", item.id)
                    return {
                        "invitation": self._payload(item),
                        "membership": GroupService._membership_payload(membership),
                        "idempotent": False,
                    }
            except IntegrityError as exc:
                raise GroupServiceError("group_invitation_conflict", 409) from exc
