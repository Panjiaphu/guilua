from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.config import Settings
from app.db import Base
from app.group_v3.auth import GroupActor
from app.handoff.v3 import GroupHandoffV3Error, parse_group_handoff_v3
from app.integrations.timeblock.client import TimeblockIntegrationError
from app.main import create_app
from app.models import (
    GroupAuditEvent,
    GroupIdempotencyRecord,
    GroupMediaParticipant,
    GroupMediaSession,
    GroupMembership,
    GroupMessage,
    GroupRadioParticipant,
    GroupRadioSession,
    GroupSpace,
)
from tests.test_group_radio_floor_v3 import FakeAsyncRedis


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ORIGIN = "http://127.0.0.1:8000"
TIMEBLOCK_ORIGIN = "http://127.0.0.1:5000"
SCOPES = [
    "group.spaces.read",
    "group.spaces.write",
    "group.messages.read",
    "group.messages.write",
    "group.media.use",
    "group.translation.use",
    "group.radio.use",
]
AI_ENTITLEMENT = {
    "group_communication": True,
    "authorization_authority": "ai-communication",
    "billing_subject": "member:42:42",
}


def _settings(tmp_path, **overrides):
    values = {
        "app_env": "test",
        "debug": True,
        "public_base_url": PUBLIC_ORIGIN,
        "timeblock_app_url": TIMEBLOCK_ORIGIN,
        "allowed_timeblock_handoff_origins": TIMEBLOCK_ORIGIN,
        "group_v3_enabled": True,
        "database_url": f"sqlite:///{(tmp_path / 'group-v3.sqlite3').as_posix()}",
        "group_message_encryption_key": "ab" * 32,
        "group_media_enabled": False,
        "group_translation_enabled": False,
        "group_radio_v3_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


def _future(seconds=3600):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _handoff_payload(surface="chat"):
    return {
        "contract_version": "3",
        "authority": "timeblock-identity",
        "group_authority": "ai-communication",
        "launch_authorized": True,
        "handoff_id": "handoff-v3-000000000000000000000001",
        "surface": surface,
        "source_origin": TIMEBLOCK_ORIGIN,
        "target_origin": PUBLIC_ORIGIN,
        "issuer": "timeblock",
        "audience": "ai-communication-group-v3",
        "principal": {
            "type": "member",
            "id": "42",
            "user_id": "42",
            "display_name": "Nguyen Minh",
            "locale": "vi",
        },
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": _future(90),
        "session_expires_at": _future(),
    }


def test_group_handoff_parser_uses_ai_owned_default_surface(tmp_path):
    handoff = parse_group_handoff_v3(_handoff_payload("plugin"), _settings(tmp_path))
    assert handoff.surface == "chat"


def test_group_handoff_parser_accepts_generic_payload_without_surface(tmp_path):
    payload = _handoff_payload("radio")
    payload.pop("surface")
    handoff = parse_group_handoff_v3(payload, _settings(tmp_path))
    assert handoff.surface == "chat"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("contract_version", "2", "invalid_contract_version"),
        ("audience", "wrong-audience", "invalid_audience"),
        ("source_origin", "https://wrong.example", "invalid_source_origin"),
        ("principal", {}, "invalid_principal_type"),
        (
            "expires_at",
            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            "expired_expires_at",
        ),
    ],
)
def test_group_handoff_v3_fails_closed_on_malformed_identity_contract(
    tmp_path, field, value, error
):
    payload = _handoff_payload("chat")
    payload[field] = value
    with pytest.raises(GroupHandoffV3Error, match=error):
        parse_group_handoff_v3(payload, _settings(tmp_path))


class RedeemStub:
    async def redeem_group_handoff_v3(self, handoff_code, **kwargs):
        assert handoff_code == "h" * 64
        assert kwargs == {
            "source_origin": TIMEBLOCK_ORIGIN,
            "target_origin": PUBLIC_ORIGIN,
            "audience": "ai-communication-group-v3",
        }
        return _handoff_payload("chat")

    async def aclose(self):
        return None


class ReplayRejectingRedeemStub(RedeemStub):
    def __init__(self):
        self.used = False

    async def redeem_group_handoff_v3(self, handoff_code, **kwargs):
        if self.used:
            raise TimeblockIntegrationError("group_handoff_replayed")
        self.used = True
        return await super().redeem_group_handoff_v3(handoff_code, **kwargs)


def _native_app(tmp_path, **overrides):
    app = create_app(_settings(tmp_path, **overrides))
    Base.metadata.create_all(app.state.database.engine)
    return app


def test_sqlite_enables_foreign_keys(tmp_path):
    app = _native_app(tmp_path)
    with app.state.database.engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_group_space_create_rolls_back_all_rows_when_audit_fails(tmp_path, monkeypatch):
    app = _native_app(tmp_path)
    principal = _handoff_payload()["principal"]
    actor = GroupActor(
        principal_type=principal["type"],
        principal_id=principal["id"],
        principal_user_id=principal["user_id"],
        display_name=principal["display_name"],
        locale=principal["locale"],
        scope=frozenset(SCOPES),
        handoff_id="forced-rollback-handoff",
        surface="chat",
        entitlement=AI_ENTITLEMENT,
    )

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("forced-audit-failure")

    monkeypatch.setattr(app.state.group_service, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="forced-audit-failure"):
        app.state.group_service.create_space(
            actor,
            {"title": "Rollback space", "description": "must not persist"},
            "rollback-space-0001",
        )

    with app.state.database.session() as db:
        assert db.scalar(select(GroupSpace)) is None
        assert db.scalar(select(GroupMembership)) is None
        assert db.scalar(select(GroupAuditEvent)) is None
        assert db.scalar(select(GroupIdempotencyRecord)) is None


def test_handoff_consume_is_exact_origin_httponly_and_secret_free(tmp_path):
    app = _native_app(tmp_path)
    app.state.timeblock_client = RedeemStub()
    with TestClient(app) as client:
        denied = client.post(
            "/api/group-handoff/v3/consume",
            json={"handoff_code": "h" * 64, "source_origin": TIMEBLOCK_ORIGIN},
            headers={"Origin": "https://evil.example"},
        )
        assert denied.status_code == 403

        response = client.post(
            "/api/group-handoff/v3/consume",
            json={"handoff_code": "h" * 64, "source_origin": TIMEBLOCK_ORIGIN},
            headers={"Origin": PUBLIC_ORIGIN},
        )
        assert response.status_code == 200
        assert response.json()["authority"] == "ai-communication"
        assert "h" * 64 not in response.text
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "Path=/" in cookie
        assert response.headers["Cache-Control"].startswith("no-store")

        session = client.get("/api/group/session")
        assert session.status_code == 200
        assert session.json()["surface"] == "chat"
        assert session.json()["entitlement"]["authorization_authority"] == "ai-communication"
        assert "group.messages.write" in session.json()["scope"]


def test_handoff_receiver_rejects_replay_and_malformed_json(tmp_path):
    app = _native_app(tmp_path)
    app.state.timeblock_client = ReplayRejectingRedeemStub()
    body = {
        "handoff_code": "h" * 64,
        "source_origin": TIMEBLOCK_ORIGIN,
    }
    with TestClient(app) as client:
        first = client.post(
            "/api/group-handoff/v3/consume",
            json=body,
            headers={"Origin": PUBLIC_ORIGIN},
        )
        replay = client.post(
            "/api/group-handoff/v3/consume",
            json=body,
            headers={"Origin": PUBLIC_ORIGIN},
        )
        malformed = client.post(
            "/api/group-handoff/v3/consume",
            content=b"{",
            headers={"Origin": PUBLIC_ORIGIN, "Content-Type": "application/json"},
        )

    assert first.status_code == 200
    assert replay.status_code == 502
    assert replay.json()["detail"] == "group_handoff_redeem_failed"
    assert malformed.status_code == 400
    assert malformed.json()["detail"] == "invalid_json"


def test_handoff_consume_ignores_legacy_capability_selector(tmp_path):
    app = _native_app(tmp_path)
    app.state.timeblock_client = RedeemStub()
    with TestClient(app) as client:
        response = client.post(
            "/api/group-handoff/v3/consume",
            json={
                "handoff_code": "h" * 64,
                "source_origin": TIMEBLOCK_ORIGIN,
                "surface": "radio",
            },
            headers={"Origin": PUBLIC_ORIGIN},
        )
    assert response.status_code == 200
    assert response.json()["surface"] == "chat"


def test_native_space_and_message_are_idempotent_and_encrypted_at_rest(tmp_path):
    app = _native_app(tmp_path)
    session = app.state.bff_session_store.create_group_session(
        principal=_handoff_payload()["principal"],
        scope=SCOPES,
        expires_at=_future(),
        handoff_id="handoff-v3-native-chat",
        surface="chat",
        entitlement=AI_ENTITLEMENT,
    )
    headers = {"Origin": PUBLIC_ORIGIN, "Idempotency-Key": "create-space-0001"}
    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, session.session_id)
        created = client.post(
            "/api/group/spaces",
            json={"title": "Dieu phoi kho van", "description": "Native V3"},
            headers=headers,
        )
        assert created.status_code == 201
        space_id = created.json()["space"]["id"]
        repeated = client.post(
            "/api/group/spaces",
            json={"title": "Dieu phoi kho van", "description": "Native V3"},
            headers=headers,
        )
        assert repeated.status_code == 200
        assert repeated.json()["idempotent"] is True
        assert repeated.json()["space"]["id"] == space_id
        mismatch = client.post(
            "/api/group/spaces",
            json={"title": "Dieu phoi kho van", "description": "different payload"},
            headers=headers,
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"] == "idempotency_payload_mismatch"

        message_headers = {"Origin": PUBLIC_ORIGIN, "Idempotency-Key": "message-client-0001"}
        body = {
            "content": "Xe so 3 da toi cua so 2",
            "content_type": "text",
            "client_message_id": "client-message-0001",
        }
        sent = client.post(f"/api/group/spaces/{space_id}/messages", json=body, headers=message_headers)
        assert sent.status_code == 201
        assert sent.json()["message"]["content"] == body["content"]
        duplicate = client.post(f"/api/group/spaces/{space_id}/messages", json=body, headers=message_headers)
        assert duplicate.status_code == 200
        assert duplicate.json()["idempotent"] is True

    with app.state.database.session() as db:
        stored_space = db.get(GroupSpace, space_id)
        assert stored_space is not None
        owner = db.scalar(
            select(GroupMembership).where(
                GroupMembership.space_id == space_id,
                GroupMembership.principal_id == "42",
                GroupMembership.role == "owner",
                GroupMembership.status == "active",
            )
        )
        assert owner is not None
        audit = db.scalar(
            select(GroupAuditEvent).where(
                GroupAuditEvent.space_id == space_id,
                GroupAuditEvent.event_type == "space.created",
            )
        )
        assert audit is not None
        assert audit.resource_id == space_id
        idempotency = db.scalar(
            select(GroupIdempotencyRecord).where(
                GroupIdempotencyRecord.endpoint == "group.spaces.create",
                GroupIdempotencyRecord.idempotency_key == "create-space-0001",
            )
        )
        assert idempotency is not None
        stored = db.scalar(select(GroupMessage))
        assert stored is not None
        assert body["content"].encode("utf-8") not in stored.content_ciphertext
        assert stored.encryption_version == "aes-256-gcm-v1"


def test_native_radio_floor_media_grant_stop_and_leave_are_end_to_end(tmp_path):
    app = _native_app(
        tmp_path,
        group_media_enabled=True,
        group_livekit_url="wss://group-v3.livekit.cloud",
        group_livekit_api_key="livekit-api-key",
        group_livekit_api_secret="livekit-api-secret",
        group_radio_v3_enabled=True,
        group_radio_redis_url="redis://group-radio.test:6379",
    )
    app.state.group_radio_floor._client = FakeAsyncRedis()
    session = app.state.bff_session_store.create_group_session(
        principal=_handoff_payload("radio")["principal"],
        scope=SCOPES,
        expires_at=_future(),
        handoff_id="handoff-v3-native-radio",
        surface="radio",
        entitlement=AI_ENTITLEMENT,
    )
    headers = {"Origin": PUBLIC_ORIGIN}

    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, session.session_id)
        created_space = client.post(
            "/api/group/spaces",
            json={"title": "Dieu phoi radio", "description": "Native Radio V3"},
            headers={**headers, "Idempotency-Key": "radio-space-0001"},
        )
        assert created_space.status_code == 201
        space_id = created_space.json()["space"]["id"]

        invitee = client.post(
            f"/api/group/spaces/{space_id}/memberships",
            json={
                "principal_type": "member",
                "principal_id": "84",
                "principal_user_id": "84",
                "display_name": "Tran An",
                "role": "member",
            },
            headers=headers,
        )
        assert invitee.status_code == 201
        invitee_id = invitee.json()["membership"]["id"]

        created_radio = client.post(
            f"/api/group/spaces/{space_id}/radio/sessions",
            json={"title": "Kenh van hanh", "participant_membership_ids": [invitee_id]},
            headers=headers,
        )
        assert created_radio.status_code == 201
        radio_id = created_radio.json()["session"]["id"]
        with app.state.database.session() as db:
            radio_row = db.get(GroupRadioSession, radio_id)
            assert radio_row is not None
            participants = list(
                db.scalars(
                    select(GroupRadioParticipant).where(
                        GroupRadioParticipant.radio_session_id == radio_id
                    )
                )
            )
            assert len(participants) == 2
            assert any(item.membership_id == invitee_id and item.status == "invited" for item in participants)
            radio_audit = db.scalar(
                select(GroupAuditEvent).where(
                    GroupAuditEvent.space_id == space_id,
                    GroupAuditEvent.event_type == "radio.session_created",
                    GroupAuditEvent.resource_id == radio_id,
                )
            )
            assert radio_audit is not None

        acquired = client.post(
            f"/api/group/spaces/{space_id}/radio/sessions/{radio_id}/floor/acquire",
            json={"source_language": "vi", "target_languages": []},
            headers=headers,
        )
        assert acquired.status_code == 201
        floor_token = acquired.json()["floor_token"]
        assert acquired.json()["burst"]["state"] == "talking"

        grant = client.post(
            f"/api/group/spaces/{space_id}/radio/sessions/{radio_id}/media-grant",
            json={"mode": "talk", "floor_token": floor_token},
            headers=headers,
        )
        assert grant.status_code == 200
        assert grant.json()["grant"]["publish_mode"] == "talk"
        assert grant.json()["grant"]["provider"] == "livekit-cloud"

        stopped = client.post(
            f"/api/group/spaces/{space_id}/radio/sessions/{radio_id}/floor/stop",
            json={"floor_token": floor_token},
            headers=headers,
        )
        assert stopped.status_code == 200
        assert stopped.json()["floor_released_before_downstream"] is True
        assert stopped.json()["burst"]["state"] == "final"

        history = client.get(
            f"/api/group/spaces/{space_id}/radio/sessions/{radio_id}/history"
        )
        assert history.status_code == 200
        assert history.json()["bursts"][0]["state"] == "final"

        left = client.post(
            f"/api/group/spaces/{space_id}/radio/sessions/{radio_id}/leave",
            headers=headers,
        )
        assert left.status_code == 200
        assert left.json()["ended_for_all"] is False


def test_group_media_join_stays_ringing_until_provider_connection(tmp_path):
    app = _native_app(
        tmp_path,
        group_media_enabled=True,
        group_livekit_url="wss://group-v3.livekit.cloud",
        group_livekit_api_key="livekit-api-key",
        group_livekit_api_secret="livekit-api-secret",
    )
    owner_session = app.state.bff_session_store.create_group_session(
        principal=_handoff_payload("video")["principal"],
        scope=SCOPES,
        expires_at=_future(),
        handoff_id="media-owner-handoff",
        surface="video",
        entitlement=AI_ENTITLEMENT,
    )
    invitee_principal = {
        "type": "member",
        "id": "84",
        "user_id": "84",
        "display_name": "Tran An",
        "locale": "en",
    }
    invitee_session = app.state.bff_session_store.create_group_session(
        principal=invitee_principal,
        scope=SCOPES,
        expires_at=_future(),
        handoff_id="media-invitee-handoff",
        surface="video",
        entitlement=AI_ENTITLEMENT,
    )
    headers = {"Origin": PUBLIC_ORIGIN}

    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, owner_session.session_id)
        created_space = client.post(
            "/api/group/spaces",
            json={"title": "Media lifecycle", "description": "Two-phase join"},
            headers={**headers, "Idempotency-Key": "media-space-0001"},
        )
        assert created_space.status_code == 201
        space_id = created_space.json()["space"]["id"]
        invitee = client.post(
            f"/api/group/spaces/{space_id}/memberships",
            json={
                "principal_type": "member",
                "principal_id": "84",
                "principal_user_id": "84",
                "display_name": "Tran An",
                "role": "member",
            },
            headers=headers,
        )
        assert invitee.status_code == 201
        invitee_membership_id = invitee.json()["membership"]["id"]
        created = client.post(
            f"/api/group/spaces/{space_id}/sessions",
            json={"media_kind": "video", "title": "Media lifecycle", "participant_membership_ids": [invitee_membership_id]},
            headers=headers,
        )
        assert created.status_code == 201
        session_id = created.json()["session"]["id"]
        assert created.json()["session"]["status"] == "ringing"
        owner_participant = next(item for item in created.json()["session"]["participants"] if item["membership_id"] != invitee_membership_id)
        assert owner_participant["invite_status"] == "joined"
        assert owner_participant["connection_status"] == "not_connected"

        client.cookies.set(app.state.settings.guilua_session_cookie, invitee_session.session_id)
        joined = client.post(
            f"/api/group/spaces/{space_id}/sessions/{session_id}/join",
            headers=headers,
        )
        assert joined.status_code == 200
        assert joined.json()["session"]["status"] == "ringing"
        invitee_participant = next(item for item in joined.json()["session"]["participants"] if item["membership_id"] == invitee_membership_id)
        assert invitee_participant["invite_status"] == "joined"
        assert invitee_participant["connection_status"] == "not_connected"

        connecting = client.post(
            f"/api/group/spaces/{space_id}/sessions/{session_id}/connection-state",
            json={"status": "connecting"},
            headers=headers,
        )
        assert connecting.status_code == 200
        assert connecting.json()["session"]["status"] == "ringing"

        grant = client.post(
            f"/api/group/spaces/{space_id}/sessions/{session_id}/media-grant",
            headers=headers,
        )
        assert grant.status_code == 200
        assert grant.json()["grant"]["provider"] == "livekit-cloud"

        connected = client.post(
            f"/api/group/spaces/{space_id}/sessions/{session_id}/connection-state",
            json={"status": "connected"},
            headers=headers,
        )
        assert connected.status_code == 200
        assert connected.json()["session"]["status"] == "active"
        invitee_participant = next(item for item in connected.json()["session"]["participants"] if item["membership_id"] == invitee_membership_id)
        assert invitee_participant["connection_status"] == "connected"


def _create_two_member_media_scenario(tmp_path, suffix: str):
    app = _native_app(
        tmp_path,
        group_media_enabled=True,
        group_livekit_url="wss://group-v3.livekit.cloud",
        group_livekit_api_key="livekit-api-key",
        group_livekit_api_secret="livekit-api-secret",
    )
    owner_session = app.state.bff_session_store.create_group_session(
        principal=_handoff_payload("video")["principal"],
        scope=SCOPES,
        expires_at=_future(),
        handoff_id=f"media-owner-{suffix}",
        surface="video",
        entitlement=AI_ENTITLEMENT,
    )
    invitee_session = app.state.bff_session_store.create_group_session(
        principal={
            "type": "member",
            "id": "84",
            "user_id": "84",
            "display_name": "Tran An",
            "locale": "en",
        },
        scope=SCOPES,
        expires_at=_future(),
        handoff_id=f"media-invitee-{suffix}",
        surface="video",
        entitlement=AI_ENTITLEMENT,
    )
    return app, owner_session, invitee_session


def _seed_two_member_media(client, app, owner_session, suffix: str):
    headers = {"Origin": PUBLIC_ORIGIN}
    client.cookies.set(app.state.settings.guilua_session_cookie, owner_session.session_id)
    created_space = client.post(
        "/api/group/spaces",
        json={"title": f"Media {suffix}", "description": "Asynchronous join"},
        headers={**headers, "Idempotency-Key": f"media-space-{suffix}"},
    )
    assert created_space.status_code == 201
    space_id = created_space.json()["space"]["id"]
    invitee = client.post(
        f"/api/group/spaces/{space_id}/memberships",
        json={
            "principal_type": "member",
            "principal_id": "84",
            "principal_user_id": "84",
            "display_name": "Tran An",
            "role": "member",
        },
        headers=headers,
    )
    assert invitee.status_code == 201
    invitee_membership_id = invitee.json()["membership"]["id"]
    created = client.post(
        f"/api/group/spaces/{space_id}/sessions",
        json={
            "media_kind": "video",
            "title": f"Media {suffix}",
            "participant_membership_ids": [invitee_membership_id],
        },
        headers=headers,
    )
    assert created.status_code == 201
    return space_id, created.json()["session"]["id"], invitee_membership_id


def _media_connection_step(client, app, bff_session, space_id: str, session_id: str, status: str):
    client.cookies.set(app.state.settings.guilua_session_cookie, bff_session.session_id)
    response = client.post(
        f"/api/group/spaces/{space_id}/sessions/{session_id}/connection-state",
        json={"status": status},
        headers={"Origin": PUBLIC_ORIGIN},
    )
    assert response.status_code == 200
    return response.json()["session"]


def _media_grant(client, app, bff_session, space_id: str, session_id: str):
    client.cookies.set(app.state.settings.guilua_session_cookie, bff_session.session_id)
    response = client.post(
        f"/api/group/spaces/{space_id}/sessions/{session_id}/media-grant",
        headers={"Origin": PUBLIC_ORIGIN},
    )
    assert response.status_code == 200
    return response.json()["grant"]


@pytest.mark.parametrize(
    "connection_order,wait_seconds",
    [
        (("owner", "invitee"), 31),
        (("invitee", "owner"), 31),
        (("owner", "invitee"), 61),
        (("invitee", "owner"), 61),
    ],
    ids=[
        "video-join-a-to-b-after-30s",
        "video-join-b-to-a-after-30s",
        "video-join-a-to-b-after-60s",
        "video-join-b-to-a-after-60s",
    ],
)
def test_group_media_connection_order_converges_on_one_room(
    tmp_path, connection_order, wait_seconds
):
    app, owner_session, invitee_session = _create_two_member_media_scenario(
        tmp_path, connection_order[0]
    )
    sessions = {"owner": owner_session, "invitee": invitee_session}
    with TestClient(app) as client:
        space_id, session_id, _invitee_membership_id = _seed_two_member_media(
            client, app, owner_session, connection_order[0]
        )
        client.cookies.set(app.state.settings.guilua_session_cookie, invitee_session.session_id)
        joined = client.post(
            f"/api/group/spaces/{space_id}/sessions/{session_id}/join",
            headers={"Origin": PUBLIC_ORIGIN},
        )
        assert joined.status_code == 200

        first_actor, second_actor = connection_order
        _media_connection_step(
            client, app, sessions[first_actor], space_id, session_id, "connecting"
        )
        rooms = [_media_grant(
            client, app, sessions[first_actor], space_id, session_id
        )["room"]]
        current = _media_connection_step(
            client, app, sessions[first_actor], space_id, session_id, "connected"
        )
        assert current["id"] == session_id

        # Advance the server-visible session age deterministically instead of
        # sleeping in the suite. The second participant must still reuse the
        # exact ACTIVE session and LiveKit room after either late interval.
        old = datetime.now(timezone.utc) - timedelta(seconds=wait_seconds)
        with app.state.database.session() as db, db.begin():
            stored = db.get(GroupMediaSession, session_id)
            stored.created_at = old
            stored.updated_at = old

        _media_connection_step(
            client, app, sessions[second_actor], space_id, session_id, "connecting"
        )
        rooms.append(_media_grant(
            client, app, sessions[second_actor], space_id, session_id
        )["room"])
        current = _media_connection_step(
            client, app, sessions[second_actor], space_id, session_id, "connected"
        )
        assert current["id"] == session_id

        assert len(set(rooms)) == 1
        assert current["status"] == "active"
        assert len(current["participants"]) == 2
        assert {item["connection_status"] for item in current["participants"]} == {"connected"}


def test_group_media_simultaneous_connect_intent_converges_on_one_room(tmp_path):
    app, owner_session, invitee_session = _create_two_member_media_scenario(tmp_path, "simultaneous")
    with TestClient(app) as client:
        space_id, session_id, _invitee_membership_id = _seed_two_member_media(
            client, app, owner_session, "simultaneous"
        )
        client.cookies.set(app.state.settings.guilua_session_cookie, invitee_session.session_id)
        assert client.post(
            f"/api/group/spaces/{space_id}/sessions/{session_id}/join",
            headers={"Origin": PUBLIC_ORIGIN},
        ).status_code == 200

        # Deterministic near-simultaneous interleaving: both clients enter
        # CONNECTING before either obtains a grant or promotes the session.
        _media_connection_step(client, app, owner_session, space_id, session_id, "connecting")
        _media_connection_step(client, app, invitee_session, space_id, session_id, "connecting")
        owner_grant = _media_grant(client, app, owner_session, space_id, session_id)
        invitee_grant = _media_grant(client, app, invitee_session, space_id, session_id)
        first = _media_connection_step(client, app, invitee_session, space_id, session_id, "connected")
        final = _media_connection_step(client, app, owner_session, space_id, session_id, "connected")

        assert owner_grant["room"] == invitee_grant["room"]
        assert first["id"] == final["id"] == session_id
        assert final["status"] == "active"
        assert len(final["participants"]) == 2


def test_group_media_late_join_and_duplicate_join_keep_active_connection(tmp_path):
    app, owner_session, invitee_session = _create_two_member_media_scenario(tmp_path, "late")
    with TestClient(app) as client:
        space_id, session_id, invitee_membership_id = _seed_two_member_media(
            client, app, owner_session, "late"
        )
        _media_connection_step(client, app, owner_session, space_id, session_id, "connecting")
        owner_grant = _media_grant(client, app, owner_session, space_id, session_id)
        active = _media_connection_step(client, app, owner_session, space_id, session_id, "connected")
        assert active["status"] == "active"

        old = datetime.now(timezone.utc) - timedelta(seconds=61)
        with app.state.database.session() as db, db.begin():
            stored = db.get(GroupMediaSession, session_id)
            stored.created_at = old
            stored.updated_at = old

        client.cookies.set(app.state.settings.guilua_session_cookie, invitee_session.session_id)
        late_join = client.post(
            f"/api/group/spaces/{space_id}/sessions/{session_id}/join",
            headers={"Origin": PUBLIC_ORIGIN},
        )
        assert late_join.status_code == 200
        assert late_join.json()["session"]["status"] == "active"
        _media_connection_step(client, app, invitee_session, space_id, session_id, "connecting")
        late_grant = _media_grant(client, app, invitee_session, space_id, session_id)
        connected = _media_connection_step(client, app, invitee_session, space_id, session_id, "connected")

        repeated = client.post(
            f"/api/group/spaces/{space_id}/sessions/{session_id}/join",
            headers={"Origin": PUBLIC_ORIGIN},
        )
        assert repeated.status_code == 200
        repeated_session = repeated.json()["session"]
        invitee = next(
            item for item in repeated_session["participants"]
            if item["membership_id"] == invitee_membership_id
        )
        assert owner_grant["room"] == late_grant["room"]
        assert connected["id"] == repeated_session["id"] == session_id
        assert invitee["invite_status"] == "joined"
        assert invitee["connection_status"] == "connected"
        assert len(repeated_session["participants"]) == 2
        with app.state.database.session() as db:
            assert db.scalar(select(GroupMediaSession).where(GroupMediaSession.id == session_id)) is not None
            assert len(list(db.scalars(select(GroupMediaParticipant).where(
                GroupMediaParticipant.session_id == session_id
            )).all())) == 2


def test_native_routes_and_ui_enforce_v3_safety_boundaries():
    app = create_app(Settings(app_env="test", debug=True))
    route_paths = set(app.openapi()["paths"])
    assert "/api/group-handoff/v3/consume" in route_paths
    assert "/api/group/spaces" in route_paths
    assert "/api/group/spaces/{space_id}/messages/{message_id}/translation" in route_paths
    assert "/api/group-translation/session" not in route_paths

    template = (ROOT / "app/templates/group_communication_v3.html").read_text(encoding="utf-8")
    direct_template = (ROOT / "app/templates/communication.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app/static/group-v3/group_v3_app.js").read_text(encoding="utf-8")
    device_manager_js = (ROOT / "app/static/group-v3/group_device_manager.js").read_text(encoding="utf-8")
    runtime_css = (ROOT / "app/static/group-v3/group_v3_runtime.css").read_text(encoding="utf-8")
    group_css = (ROOT / "app/static/group-v3/group_v3.css").read_text(encoding="utf-8")
    translation_js = (ROOT / "app/static/group-v3/group_v3_translation.js").read_text(encoding="utf-8")
    tts_manager_js = (ROOT / "app/static/group-v3/group_tts_manager.js").read_text(encoding="utf-8")
    presentation_js = (ROOT / "app/static/group-v3/group_media_presentation.js").read_text(encoding="utf-8")
    workspace_js = (ROOT / "app/static/group-v3/group_communication_workspace.js").read_text(encoding="utf-8")
    radio_ui_js = (ROOT / "app/static/group-v3/group_radio_ui.js").read_text(encoding="utf-8")
    i18n_js = (ROOT / "app/static/group-v3/group_v3_i18n.js").read_text(encoding="utf-8")
    radio_router = (ROOT / "app/group_v3/radio_router.py").read_text(encoding="utf-8")

    assert "group_v3_app.js" in template
    assert "group_v3_app.js" not in direct_template
    assert "group_handoff.js" not in direct_template
    assert "localStorage" not in app_js + translation_js
    assert "sessionStorage" not in app_js + translation_js
    assert "OPENAI_API_KEY" not in app_js + translation_js + template
    assert "https://api.openai.com/v1/realtime/calls" not in translation_js
    assert "RTCPeerConnection" not in translation_js
    assert "MediaStream([track])" in translation_js
    assert "data-group-translation-v2" in app_js
    connect_media = app_js[
        app_js.index("async function connectMedia") : app_js.index("async function connectRadio")
    ]
    assert "state.mediaSession.status !== \"active\" && state.mediaSession.status !== \"ringing\"" in connect_media
    assert connect_media.index('updateMediaConnectionState("connecting", "", context)') < connect_media.index("connectWithGrant")
    assert 'return "call:" + String(' in app_js
    assert "RoomEvent.AudioPlaybackStatusChanged" in app_js
    assert "room.startAudio()" in app_js
    assert "group-v3:audio-playback-blocked" in presentation_js
    assert "resumeAudio" in presentation_js
    assert 'managerState = "LOCKED"' in tts_manager_js
    assert 'setManagerState("UNLOCK_REQUIRED"' in tts_manager_js
    assert 'setManagerState("VOICE_LOADING")' in tts_manager_js
    assert 'setManagerState("READY")' in tts_manager_js
    assert 'setManagerState("PLAYING")' in tts_manager_js
    assert 'setManagerState("UNSUPPORTED"' in tts_manager_js
    assert '.call-communication-layout' in workspace_js
    assert "roomPicker: roomPicker" in radio_ui_js
    select_space = app_js[
        app_js.index("async function selectSpace") : app_js.index("async function createSpace")
    ]
    assert select_space.index('/leave", { method: "POST" }') < select_space.index("disconnectMedia(false)")
    assert "if (publish)" in app_js and "getUserMedia" in device_manager_js
    assert "group_device_manager.js?v=20260904-prejoin-1" in template
    assert "data-media-member-search" in app_js and "data-media-no-results" in app_js
    assert "data-media-member-search" in app_js[app_js.index("function inviteForm"):app_js.index("function callDock")]
    assert "width: min(760px, calc(100% - 48px))" in runtime_css
    assert "max-height: min(38dvh, 300px)" in runtime_css
    assert ".chat-content.state-active_video { grid-template-rows: minmax(0, 1fr) auto; }" in group_css
    assert "speechSynthesis" in tts_manager_js
    assert "private_audio_playback\": \"suppressed" in radio_router
    assert radio_router.index("group_radio_floor.release") < radio_router.index("stop_burst_after_floor_release")
    assert '["chat-translation", "languages", "chatTranslation"]' in app_js
    assert 'data-surface="radio-translation"' not in app_js
    assert '/group/chat-translation?tab=radio' in app_js
    assert 'chatTranslation:' in i18n_js
    assert 'radioTranslation:' in i18n_js
    assert "const vi =" in i18n_js
    assert "const en =" in i18n_js
    assert "const zhTW =" in i18n_js
    assert "AI-COMMUNICATION lưu bền thành viên" in i18n_js
    assert "AI-COMMUNICATION durably stores memberships" in i18n_js
    assert "AI-COMMUNICATION 會持久保存成員資格" in i18n_js
    assert "Timeblock durably stores" not in i18n_js
    assert "Timeblock lưu bền" not in i18n_js
    assert 'group_v3_i18n.js?v=20260907-group-collaboration-1' in template
    assert 'group_v3_app.js?v=20260907-group-collaboration-1' in template
    assert 'class="logout-navigation"' in app_js
    assert 'mobileLogout: logout' in app_js
    assert "logout: 'Đăng xuất'" in i18n_js
    assert "logout: 'Log out'" in i18n_js
    assert "logout: '登出'" in i18n_js


def test_generic_handoff_receiver_has_no_capability_selector_or_browser_secret_storage():
    root_receiver = (ROOT / "app/static/js/group_handoff_root_receiver.js").read_text(
        encoding="utf-8"
    )
    native_receiver = (ROOT / "app/static/group-ui/group_handoff_v3.js").read_text(
        encoding="utf-8"
    )
    assert "transport: \"postmessage-memory\"" in root_receiver
    assert 'body: JSON.stringify({ handoff_code: handoffCode, source_origin: sourceOrigin })' in root_receiver
    assert (
        'if (message.transport !== undefined && message.transport !== "postmessage-memory") return false;'
        in root_receiver
    )
    assert 'if (message.transport !== "postmessage-memory") return false;' in native_receiver
    assert 'const compatibleSurfaces = Object.freeze(["chat", "call", "video", "radio", "plugin"]);' in root_receiver
    assert "surface," in root_receiver
    assert "window.location.replace(\"/group\")" in root_receiver
    assert "surface: text(message.surface" not in root_receiver
    assert "surface: text(message.surface" not in native_receiver
    assert "runtimeConfig.initial_surface" not in native_receiver
    assert "localStorage" not in root_receiver + native_receiver
    assert "sessionStorage" not in root_receiver + native_receiver


def test_normal_group_path_can_select_surface_after_handoff(tmp_path):
    app = _native_app(tmp_path)
    session = app.state.bff_session_store.create_group_session(
        principal=_handoff_payload("chat")["principal"],
        scope=SCOPES,
        expires_at=_future(),
        handoff_id="normal-group-navigation",
        surface="chat",
        entitlement=AI_ENTITLEMENT,
    )
    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, session.session_id)
        response = client.get("/group/radio?lang=en")

    assert response.status_code == 200
    assert 'id="group-native-app"' in response.text
    assert '"initial_surface": "radio"' in response.text
    assert '"group_authorized": true' in response.text


def test_group_chat_translation_migration_is_single_head_and_reversible_source():
    migration = (
        ROOT / "alembic/versions/20260902_0018_group_v3_chat_translation.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "20260902_0018"' in migration
    assert 'down_revision = "20260901_0017"' in migration
    assert 'op.create_table(\n        "group_chat_translations"' in migration
    assert 'op.add_column(\n        "group_messages"' in migration
    assert 'op.drop_table("group_chat_translations")' in migration
    assert 'op.drop_column("group_messages", "source_language")' in migration


def test_group_invitation_migration_advances_single_head_and_is_reversible_source():
    migration = (
        ROOT / "alembic/versions/20260903_0019_group_v3_invitations.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "20260903_0019"' in migration
    assert 'down_revision = "20260902_0018"' in migration
    assert '"group_invitations"' in migration
    assert 'op.drop_table("group_invitations")' in migration


def test_group_media_connection_migration_advances_single_head_and_is_reversible_source():
    migration = (
        ROOT / "alembic/versions/20260904_0020_group_media_connection_state.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "20260904_0020"' in migration
    outbox_migration = (
        ROOT / "alembic/versions/20260904_0021_group_event_outbox.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "20260904_0021"' in outbox_migration
    assert "group_event_outbox" in outbox_migration
    assert 'down_revision = "20260903_0019"' in migration
    assert '"connection_status"' in migration
    assert '"connection_error_code"' in migration
    assert 'op.create_check_constraint(' in migration
    assert 'op.drop_constraint(' in migration
    assert 'op.drop_column("group_media_participants", "connection_status")' in migration


def test_group_owner_invariant_migration_is_present_and_reversible_source():
    migration = (ROOT / "alembic/versions/20260904_0022_group_owner_invariant.py").read_text(encoding="utf-8")
    assert 'revision = "20260904_0022"' in migration
    assert 'down_revision = "20260904_0021"' in migration
    assert "uq_group_memberships_active_owner" in migration
    assert "sqlite_where" in migration and "postgresql_where" in migration
    assert 'op.drop_index("uq_group_memberships_active_owner"' in migration


def test_group_translation_v2_migration_is_single_head_and_encrypted_source_only():
    migration = (ROOT / "alembic/versions/20260904_0023_group_translation_v2.py").read_text(encoding="utf-8")
    assert 'revision = "20260904_0023"' in migration
    assert 'down_revision = "20260904_0022"' in migration
    assert "group_translation_segments" in migration
    assert "group_translation_variants" in migration
    assert "source_ciphertext" in migration and "translated_ciphertext" in migration
