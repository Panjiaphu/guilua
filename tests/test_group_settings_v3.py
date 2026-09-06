from __future__ import annotations

from sqlalchemy import select
from fastapi.testclient import TestClient

from app.models import GroupMembership
from tests.test_group_v3_native import (
    AI_ENTITLEMENT,
    PUBLIC_ORIGIN,
    SCOPES,
    _future,
    _handoff_payload,
    _native_app,
)


def _session(app, principal, handoff_id):
    return app.state.bff_session_store.create_group_session(
        principal=principal,
        scope=SCOPES,
        expires_at=_future(),
        handoff_id=handoff_id,
        surface="chat",
        entitlement=AI_ENTITLEMENT,
    )


def _headers():
    return {"Origin": PUBLIC_ORIGIN}


def test_owner_transfer_is_atomic_and_old_owner_becomes_admin(tmp_path):
    app = _native_app(tmp_path)
    owner_principal = _handoff_payload()["principal"]
    member_principal = {
        "type": "member", "id": "transfer-member", "user_id": "transfer-member",
        "display_name": "Transfer target", "locale": "vi",
    }
    owner = _session(app, owner_principal, "settings-owner")
    _session(app, member_principal, "settings-target")
    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, owner.session_id)
        space = client.post(
            "/api/group/spaces",
            json={"title": "Ownership", "description": "settings"},
            headers={**_headers(), "Idempotency-Key": "ownership-space-1"},
        ).json()["space"]
        target = client.post(
            f"/api/group/spaces/{space['id']}/memberships",
            json={
                "principal_type": "member", "principal_id": "transfer-member",
                "principal_user_id": "transfer-member", "display_name": "Transfer target",
                "role": "member",
            },
            headers=_headers(),
        ).json()["membership"]
        transferred = client.post(
            f"/api/group/spaces/{space['id']}/ownership/transfer",
            json={"target_membership_id": target["id"], "version": space["version"]},
            headers=_headers(),
        )
        assert transferred.status_code == 200
        assert transferred.json()["space"]["my_role"] == "admin"
        rows = client.get(f"/api/group/spaces/{space['id']}/memberships").json()["memberships"]
        assert [row["role"] for row in rows if row["status"] == "active"].count("owner") == 1
        assert next(row for row in rows if row["id"] == target["id"])["role"] == "owner"
        denied = client.post(
            f"/api/group/spaces/{space['id']}/ownership/transfer",
            json={"target_membership_id": target["id"], "version": space["version"] + 1},
            headers=_headers(),
        )
        assert denied.status_code == 403


def test_owner_delete_soft_deletes_space_and_revokes_memberships(tmp_path):
    app = _native_app(tmp_path)
    owner = _session(app, _handoff_payload()["principal"], "delete-owner")
    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, owner.session_id)
        space = client.post(
            "/api/group/spaces",
            json={"title": "Delete me", "description": "temporary"},
            headers={**_headers(), "Idempotency-Key": "delete-space-1"},
        ).json()["space"]
        deleted = client.delete(
            f"/api/group/spaces/{space['id']}?version={space['version']}",
            headers=_headers(),
        )
        assert deleted.status_code == 200
        assert deleted.json()["space"]["lifecycle_status"] == "deleted"
        assert client.get("/api/group/spaces").json()["spaces"] == []
        # Deleted spaces intentionally remain concealed behind the membership guard.
        assert client.get(f"/api/group/spaces/{space['id']}").status_code == 403
    with app.state.database.session() as db:
        rows = db.scalars(select(GroupMembership).where(GroupMembership.space_id == space["id"])).all()
        assert rows and all(item.status == "removed" for item in rows)
