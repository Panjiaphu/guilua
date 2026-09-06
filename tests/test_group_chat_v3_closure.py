from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import GroupAttachment
from tests.test_group_v3_native import (
    AI_ENTITLEMENT,
    PUBLIC_ORIGIN,
    SCOPES,
    _future,
    _handoff_payload,
    _native_app,
)


class RecordingEventBroker:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []

    async def publish(self, space_id: str, event_type: str, *, resource_id="") -> None:
        self.events.append((space_id, event_type, str(resource_id)))


def _session(app, principal: dict[str, str], handoff_id: str):
    return app.state.bff_session_store.create_group_session(
        principal=principal,
        scope=SCOPES,
        expires_at=_future(),
        handoff_id=handoff_id,
        surface="chat",
        entitlement={
            **AI_ENTITLEMENT,
            "billing_subject": (
                f"{principal['type']}:{principal['id']}:{principal['user_id']}"
            ),
        },
    )


def test_two_identity_group_chat_persists_full_native_history_and_denies_outsider(
    tmp_path,
):
    app = _native_app(tmp_path)
    broker = RecordingEventBroker()
    app.state.group_event_broker = broker
    owner = _session(app, _handoff_payload("chat")["principal"], "chat-owner")
    invitee_principal = {
        "type": "member",
        "id": "84",
        "user_id": "84",
        "display_name": "Tran An",
        "locale": "en",
    }
    outsider_principal = {
        "type": "member",
        "id": "999",
        "user_id": "999",
        "display_name": "Outside User",
        "locale": "en",
    }
    invitee = _session(app, invitee_principal, "chat-invitee")
    outsider = _session(app, outsider_principal, "chat-outsider")
    origin = {"Origin": PUBLIC_ORIGIN}
    attachment_payload = b"group-v3-private-attachment"

    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, owner.session_id)
        created = client.post(
            "/api/group/spaces",
            json={"title": "Native Group closure", "description": "Two identities"},
            headers={**origin, "Idempotency-Key": "chat-closure-space-1"},
        )
        assert created.status_code == 201
        space_id = created.json()["space"]["id"]
        membership = client.post(
            f"/api/group/spaces/{space_id}/memberships",
            json={
                "principal_type": "member",
                "principal_id": "84",
                "principal_user_id": "84",
                "display_name": "Tran An",
                "role": "member",
            },
            headers=origin,
        )
        assert membership.status_code == 201

        uploaded = client.post(
            f"/api/group/spaces/{space_id}/attachments",
            content=attachment_payload,
            headers={
                **origin,
                "X-File-Name": "dispatch.txt",
                "Content-Type": "text/plain",
            },
        )
        assert uploaded.status_code == 201
        attachment_id = uploaded.json()["attachment"]["id"]
        sent = client.post(
            f"/api/group/spaces/{space_id}/messages",
            json={
                "content": "Dispatch document",
                "content_type": "attachment",
                "client_message_id": "chat-owner-message-1",
                "source_language": "vi",
                "attachment_ids": [attachment_id],
            },
            headers={**origin, "Idempotency-Key": "chat-owner-message-1"},
        )
        assert sent.status_code == 201
        owner_message_id = sent.json()["message"]["id"]

        client.cookies.set(app.state.settings.guilua_session_cookie, invitee.session_id)
        received = client.get(f"/api/group/spaces/{space_id}/messages?limit=20")
        assert received.status_code == 200
        assert any(item["id"] == owner_message_id for item in received.json()["messages"])
        downloaded = client.get(
            f"/api/group/spaces/{space_id}/attachments/{attachment_id}"
        )
        assert downloaded.status_code == 200
        assert downloaded.content == attachment_payload
        inline_text = client.get(
            f"/api/group/spaces/{space_id}/attachments/{attachment_id}/inline"
        )
        assert inline_text.status_code == 415

        reply = client.post(
            f"/api/group/spaces/{space_id}/messages",
            json={
                "content": "Received and confirmed",
                "content_type": "text",
                "client_message_id": "chat-invitee-message-1",
                "source_language": "en",
                "attachment_ids": [],
            },
            headers={**origin, "Idempotency-Key": "chat-invitee-message-1"},
        )
        assert reply.status_code == 201
        reacted = client.post(
            f"/api/group/spaces/{space_id}/messages/{owner_message_id}/reactions",
            json={"reaction": "ack"},
            headers=origin,
        )
        assert reacted.status_code == 200
        assert reacted.json()["message"]["reactions"][0]["reaction"] == "ack"
        pinned = client.post(
            f"/api/group/spaces/{space_id}/messages/{owner_message_id}/pin",
            headers=origin,
        )
        assert pinned.status_code == 200
        pins = client.get(f"/api/group/spaces/{space_id}/pins")
        assert pins.status_code == 200
        assert pins.json()["messages"][0]["id"] == owner_message_id

        client.cookies.set(app.state.settings.guilua_session_cookie, outsider.session_id)
        denied = client.get(f"/api/group/spaces/{space_id}/messages?limit=20")
        assert denied.status_code == 403

    with TestClient(app) as reloaded:
        reloaded.cookies.set(app.state.settings.guilua_session_cookie, owner.session_id)
        history = reloaded.get(f"/api/group/spaces/{space_id}/messages?limit=20")
        assert history.status_code == 200
        assert {item["content"] for item in history.json()["messages"]} == {
            "Dispatch document",
            "Received and confirmed",
        }

    event_types = {event_type for _, event_type, _ in broker.events}
    assert {
        "space.created",
        "membership.created",
        "message.created",
        "message.reaction",
        "message.pin",
    }.issubset(event_types)
    with app.state.database.session() as db:
        stored = db.scalar(select(GroupAttachment).where(GroupAttachment.id == attachment_id))
        assert stored is not None
        assert attachment_payload not in stored.payload_ciphertext
