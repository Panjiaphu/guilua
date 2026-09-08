from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.group_v3.auth import GroupActor
from app.integrations.timeblock.client import TimeblockIntegrationError
from app.models import (
    GroupEventOutbox,
    GroupMembership,
    GroupNotificationDelivery,
)
from tests.test_group_v3_native import AI_ENTITLEMENT, SCOPES, _native_app


def _actor(identity: str) -> GroupActor:
    return GroupActor(
        principal_type="member",
        principal_id=identity,
        principal_user_id=identity,
        display_name=f"Member {identity}",
        locale="vi",
        scope=frozenset(SCOPES),
        handoff_id=f"notification-handoff-{identity}",
        surface="chat",
        entitlement={**AI_ENTITLEMENT, "billing_subject": f"member:{identity}:{identity}"},
    )


@dataclass
class FakeTimeblockNotifications:
    fail: bool = False
    push_state: str = "sent"
    calls: list[dict] = field(default_factory=list)

    async def ingest_group_notification(self, payload, *, idempotency_key):
        self.calls.append({"payload": payload, "idempotency_key": idempotency_key})
        if self.fail:
            raise TimeblockIntegrationError("timeblock_unavailable")
        return {
            "authority": "timeblock",
            "receipt": {"id": uuid4().hex, "push_state": self.push_state},
        }


@dataclass
class FakePresence:
    active: bool | None = False

    async def is_active(self, _space_id: str, _membership_id: str):
        return self.active

    async def close(self):
        return None


def _runtime(tmp_path, **settings):
    app = _native_app(tmp_path, **settings)
    timeblock = FakeTimeblockNotifications()
    presence = FakePresence()
    app.state.group_notification_service.timeblock_client = timeblock
    app.state.group_notification_service.presence = presence
    return app, timeblock, presence


def _seed_space(app):
    owner = _actor("42")
    recipient = _actor("84")
    space = app.state.group_service.create_space(
        owner,
        {"title": "Notification QA", "description": "Metadata only"},
        "notification-space-create",
    )["space"]
    membership = app.state.group_service.add_member(
        owner,
        space["id"],
        {
            "principal_type": recipient.principal_type,
            "principal_id": recipient.principal_id,
            "principal_user_id": recipient.principal_user_id,
            "display_name": recipient.display_name,
            "role": "member",
        },
    )
    return owner, recipient, space["id"], membership["id"]


def _send(
    app,
    actor,
    space_id: str,
    suffix: str,
    *,
    reply_to_id: str | None = None,
    content: str | None = None,
):
    return app.state.group_service.create_message(
        actor,
        space_id,
        {
            "content": content or f"Raw private Group content {suffix}",
            "content_type": "text",
            "client_message_id": f"notification-message-{suffix}",
            "source_language": "vi",
            "reply_to_id": reply_to_id,
        },
        f"notification-message-{suffix}",
    )["message"]


def _drain(app):
    return asyncio.run(app.state.group_notification_service.drain(limit=200))


def test_smart_first_unread_aggregates_burst_and_allows_next_cycle(tmp_path):
    app, timeblock, _presence = _runtime(tmp_path)
    owner, recipient, space_id, membership_id = _seed_space(app)

    first = _send(app, owner, space_id, "smart-first")
    _drain(app)
    second = _send(app, owner, space_id, "smart-second")
    _drain(app)

    assert len(timeblock.calls) == 1
    first_delivery = timeblock.calls[0]["payload"]
    assert first_delivery["event_kind"] == "group.chat.activity"
    assert first_delivery["push_eligible"] is False
    assert "Raw private Group content" not in str(first_delivery)
    with app.state.database.session() as db:
        member = db.get(GroupMembership, membership_id)
        assert member.unread_count == 2

    read = app.state.group_notification_service.mark_read(
        recipient, space_id, second["sequence"]
    )
    assert read["unread_count"] == 0
    _send(app, owner, space_id, "smart-next-cycle")
    _drain(app)
    assert len(timeblock.calls) == 2
    assert first["id"] != second["id"]


def test_sender_never_receives_a_self_notification(tmp_path):
    app, timeblock, _presence = _runtime(tmp_path)
    owner = _actor("42")
    space_id = app.state.group_service.create_space(
        owner,
        {"title": "Self notification QA", "description": "No echo"},
        "self-notification-space",
    )["space"]["id"]

    _send(app, owner, space_id, "sender-self")
    _drain(app)

    assert timeblock.calls == []


def test_muted_and_removed_members_receive_no_future_notification(tmp_path):
    app, timeblock, _presence = _runtime(tmp_path)
    owner, recipient, space_id, membership_id = _seed_space(app)
    app.state.group_notification_service.update_preferences(
        recipient, space_id, "smart", 60
    )

    _send(app, owner, space_id, "muted")
    _drain(app)
    assert timeblock.calls == []
    with app.state.database.session() as db:
        assert db.get(GroupMembership, membership_id).unread_count == 1

    with app.state.database.session() as db:
        with db.begin():
            membership = db.get(GroupMembership, membership_id)
            membership.status = "removed"
    _send(app, owner, space_id, "removed")
    _drain(app)

    assert timeblock.calls == []
    with app.state.database.session() as db:
        assert db.get(GroupMembership, membership_id).unread_count == 1


@pytest.mark.parametrize(
    ("mode", "expected_calls", "push_eligible"),
    [
        ("all", 1, True),
        ("important", 0, None),
        ("none", 0, None),
    ],
)
def test_per_space_modes_and_all_mode_burst_coalescing(
    tmp_path, mode: str, expected_calls: int, push_eligible: bool | None
):
    app, timeblock, _presence = _runtime(tmp_path)
    owner, recipient, space_id, membership_id = _seed_space(app)
    app.state.group_notification_service.update_preferences(
        recipient, space_id, mode, None
    )

    _send(app, owner, space_id, f"{mode}-one")
    _drain(app)
    _send(app, owner, space_id, f"{mode}-two")
    _drain(app)

    assert len(timeblock.calls) == expected_calls
    if timeblock.calls:
        assert timeblock.calls[0]["payload"]["push_eligible"] is push_eligible
    with app.state.database.session() as db:
        assert db.get(GroupMembership, membership_id).unread_count == 2


def test_same_space_presence_suppresses_alert_without_losing_unread(tmp_path):
    app, timeblock, presence = _runtime(tmp_path)
    owner, _recipient, space_id, membership_id = _seed_space(app)
    presence.active = True

    _send(app, owner, space_id, "visible")
    _drain(app)

    assert timeblock.calls == []
    with app.state.database.session() as db:
        member = db.get(GroupMembership, membership_id)
        delivery = db.scalar(select(GroupNotificationDelivery))
        assert member.unread_count == 1
        assert delivery.status == "suppressed"
        assert delivery.last_error == "same_space_visible"


def test_direct_reply_is_targeted_in_important_mode_without_regex_mentions(tmp_path):
    app, timeblock, _presence = _runtime(tmp_path)
    owner, recipient, space_id, _membership_id = _seed_space(app)
    app.state.group_notification_service.update_preferences(
        recipient, space_id, "important", None
    )

    recipient_message = _send(app, recipient, space_id, "recipient-source")
    _drain(app)
    timeblock.calls.clear()
    _send(
        app,
        owner,
        space_id,
        "mention-like-text",
        content="@Member 84 đây chỉ là văn bản, không phải structured mention",
    )
    _drain(app)
    assert timeblock.calls == []
    _send(
        app,
        owner,
        space_id,
        "owner-reply",
        reply_to_id=recipient_message["id"],
    )
    _drain(app)

    assert len(timeblock.calls) == 1
    payload = timeblock.calls[0]["payload"]
    assert payload["recipient"]["id"] == recipient.principal_id
    assert payload["event_kind"] == "group.chat.reply"
    assert payload["push_eligible"] is True


def test_timeblock_failure_is_retryable_and_never_rolls_back_group_message(tmp_path):
    app, timeblock, _presence = _runtime(tmp_path)
    owner, _recipient, space_id, _membership_id = _seed_space(app)
    timeblock.fail = True

    message = _send(app, owner, space_id, "timeblock-down")
    assert message["id"]
    _drain(app)

    with app.state.database.session() as db:
        delivery = db.scalar(select(GroupNotificationDelivery))
        assert delivery.status == "failed"
        assert delivery.attempts == 1
        assert "timeblock_unavailable" in delivery.last_error
        delivery.next_attempt_at = delivery.updated_at
        db.commit()

    first_idempotency_key = timeblock.calls[0]["idempotency_key"]
    timeblock.fail = False
    _drain(app)
    with app.state.database.session() as db:
        delivery = db.scalar(select(GroupNotificationDelivery))
        assert delivery.status == "delivered"
        assert delivery.attempts == 2
        assert delivery.delivered_at is not None
    assert len(timeblock.calls) == 2
    assert timeblock.calls[1]["idempotency_key"] == first_idempotency_key


def test_timeblock_failed_push_receipt_stays_retryable_until_terminal(tmp_path):
    app, timeblock, _presence = _runtime(tmp_path)
    owner, recipient, space_id, _membership_id = _seed_space(app)
    app.state.group_notification_service.update_preferences(
        recipient, space_id, "all", None
    )
    timeblock.push_state = "failed"

    message = _send(app, owner, space_id, "push-failed")
    assert message["id"]
    _drain(app)
    with app.state.database.session() as db:
        delivery = db.scalar(select(GroupNotificationDelivery))
        assert delivery.status == "failed"
        assert delivery.attempts == 1
        assert delivery.last_error == "timeblock_group_notification_pending"
        delivery.next_attempt_at = delivery.updated_at
        db.commit()

    idempotency_key = timeblock.calls[0]["idempotency_key"]
    timeblock.push_state = "sent"
    _drain(app)
    with app.state.database.session() as db:
        delivery = db.scalar(select(GroupNotificationDelivery))
        assert delivery.status == "delivered"
        assert delivery.attempts == 2
    assert [call["idempotency_key"] for call in timeblock.calls] == [
        idempotency_key,
        idempotency_key,
    ]


@pytest.mark.parametrize(
    ("media_kind", "incoming_kind", "missed_kind"),
    [
        ("audio", "group.call.incoming", "group.call.missed"),
        ("video", "group.video.incoming", "group.video.missed"),
    ],
)
def test_call_and_video_create_incoming_and_missed_internal_push(
    tmp_path, media_kind: str, incoming_kind: str, missed_kind: str
):
    app, timeblock, _presence = _runtime(tmp_path, group_media_enabled=True)
    owner, _recipient, space_id, membership_id = _seed_space(app)
    session = app.state.group_media_session_service.create_session(
        owner,
        space_id,
        {
            "media_kind": media_kind,
            "title": "Incoming media",
            "participant_membership_ids": [membership_id],
        },
    )
    _drain(app)
    assert [call["payload"]["event_kind"] for call in timeblock.calls] == [incoming_kind]

    app.state.group_media_session_service.end_for_all(
        owner, space_id, session["id"]
    )
    _drain(app)
    assert [call["payload"]["event_kind"] for call in timeblock.calls] == [
        incoming_kind,
        missed_kind,
    ]
    assert all(call["payload"]["push_eligible"] for call in timeblock.calls)


def test_radio_invite_notifies_once_but_ptt_lifecycle_never_notifies(tmp_path):
    app, timeblock, _presence = _runtime(tmp_path, group_radio_v3_enabled=True)
    owner, _recipient, space_id, membership_id = _seed_space(app)
    session = app.state.group_radio_service.create_session(
        owner,
        space_id,
        {"title": "Radio", "participant_membership_ids": [membership_id]},
    )
    _drain(app)
    assert [call["payload"]["event_kind"] for call in timeblock.calls] == [
        "group.radio.invited"
    ]

    with app.state.database.session() as db:
        with db.begin():
            db.add(
                GroupEventOutbox(
                    id=str(uuid4()),
                    space_id=space_id,
                    event_type="radio.floor_acquired",
                    resource_id=session["id"],
                )
            )
    _drain(app)
    assert len(timeblock.calls) == 1
