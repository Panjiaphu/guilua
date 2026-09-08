from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.group_translation.provider import (
    GroupTranslationProviderError,
    TextTranslationResult,
)
from app.group_v3.auth import GroupActor
from app.group_v3.service import GroupServiceError
from app.models import (
    GroupChatTranslation,
    GroupChatTranslationCostLedger,
    GroupChatTranslationRequest,
    GroupMembership,
)
from tests.test_group_v3_native import (
    AI_ENTITLEMENT,
    PUBLIC_ORIGIN,
    SCOPES,
    _future,
    _handoff_payload,
    _native_app,
)


@dataclass
class FakeTextProvider:
    translated_text: str
    failure_code: str = ""
    delay_seconds: float = 0

    def __post_init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def translate_text(self, **values) -> TextTranslationResult:
        self.calls.append(dict(values))
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.failure_code:
            raise GroupTranslationProviderError(self.failure_code)
        return TextTranslationResult(
            text=self.translated_text,
            model="fake-translation-model",
            request_id="provider-request-1",
        )


def _translation_runtime(tmp_path, translated_text: str):
    app = _native_app(
        tmp_path,
        group_translation_enabled=True,
        openai_api_key="render-server-key-never-sent-to-browser",
    )
    provider = FakeTextProvider(translated_text)
    app.state.group_chat_translation_service.provider = provider
    session = app.state.bff_session_store.create_group_session(
        principal=_handoff_payload("chat")["principal"],
        scope=SCOPES,
        expires_at=_future(),
        handoff_id="handoff-v3-chat-translation",
        surface="chat",
        entitlement=AI_ENTITLEMENT,
    )
    return app, session, provider


def _create_space_message_and_preferences(
    client: TestClient,
    *,
    source_language: str,
    target_language: str,
    original_text: str,
) -> tuple[str, str]:
    headers = {"Origin": PUBLIC_ORIGIN}
    space = client.post(
        "/api/group/spaces",
        json={"title": "Translation QA", "description": "Native Group Chat"},
        headers={**headers, "Idempotency-Key": "translation-space-0001"},
    )
    assert space.status_code == 201
    space_id = space.json()["space"]["id"]
    profile = client.put(
        f"/api/group/spaces/{space_id}/translation/profile",
        json={
            "spoken_language": source_language,
            "preferred_output_language": target_language,
            "auto_translate_enabled": True,
            "auto_read_enabled": False,
            "show_original_enabled": True,
        },
        headers=headers,
    )
    assert profile.status_code == 200
    consent = client.put(
        f"/api/group/spaces/{space_id}/translation/consent",
        json={"status": "granted", "policy_version": "group-translation-v3-2026-08-31"},
        headers=headers,
    )
    assert consent.status_code == 200
    sent = client.post(
        f"/api/group/spaces/{space_id}/messages",
        json={
            "content": original_text,
            "content_type": "text",
            "client_message_id": "translation-message-0001",
            "source_language": source_language,
        },
        headers={**headers, "Idempotency-Key": "translation-message-0001"},
    )
    assert sent.status_code == 201
    return space_id, sent.json()["message"]["id"]


@pytest.mark.parametrize(
    ("source_language", "target_language", "original_text", "translated_text"),
    [
        ("vi", "en", "Xin chào đội vận hành", "Hello operations team"),
        ("vi", "zh-TW", "Xe đã tới cửa số hai", "車輛已抵達二號門"),
        ("en", "vi", "The shipment is ready", "Lô hàng đã sẵn sàng"),
        ("zh-TW", "vi", "請確認交接文件", "Vui lòng xác nhận tài liệu bàn giao"),
    ],
)
def test_chat_translation_is_final_shared_idempotent_and_encrypted(
    tmp_path,
    source_language: str,
    target_language: str,
    original_text: str,
    translated_text: str,
):
    app, session, provider = _translation_runtime(tmp_path, translated_text)
    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, session.session_id)
        space_id, message_id = _create_space_message_and_preferences(
            client,
            source_language=source_language,
            target_language=target_language,
            original_text=original_text,
        )
        headers = {"Origin": PUBLIC_ORIGIN, "Idempotency-Key": "chat-translation-0001"}
        translated = client.post(
            f"/api/group/spaces/{space_id}/messages/{message_id}/translation",
            headers=headers,
        )
        assert translated.status_code == 200
        payload = translated.json()["translation"]
        assert payload["message_id"] == message_id
        assert payload["source_language"] == source_language
        assert payload["target_language"] == target_language
        assert payload["state"] == "FINAL"
        assert payload["translated_text"] == translated_text
        assert payload["shared_variant"] is True
        assert payload["cost_state"] == "settled"

        repeated = client.post(
            f"/api/group/spaces/{space_id}/messages/{message_id}/translation",
            headers=headers,
        )
        assert repeated.status_code == 200
        assert repeated.json()["idempotent"] is True
        assert repeated.json()["translation"]["id"] == payload["id"]
        assert len(provider.calls) == 1

        messages = client.get(f"/api/group/spaces/{space_id}/messages?limit=10")
        assert messages.status_code == 200
        assert messages.json()["messages"][0]["content"] == original_text
        history = client.get(
            f"/api/group/spaces/{space_id}/translation/chat-history?limit=10"
        )
        assert history.status_code == 200
        assert history.json()["translations"][0]["message_id"] == message_id
        assert history.json()["translations"][0]["translated_text"] == translated_text

    with app.state.database.session() as db:
        stored = db.scalar(select(GroupChatTranslation))
        assert stored is not None
        assert stored.status == "final"
        assert translated_text.encode("utf-8") not in stored.translated_ciphertext
        assert stored.encryption_version == "aes-256-gcm-v1"


def _actor(identity: str, *, locale: str = "en") -> GroupActor:
    return GroupActor(
        principal_type="member",
        principal_id=identity,
        principal_user_id=identity,
        display_name=f"Member {identity}",
        locale=locale,
        scope=frozenset(SCOPES),
        handoff_id=f"handoff-{identity}",
        surface="chat",
        entitlement={**AI_ENTITLEMENT, "billing_subject": f"member:{identity}:{identity}"},
    )


def _seed_shared_translation(app):
    owner = _actor("42", locale="vi")
    recipient = _actor("84", locale="en")
    space_id = app.state.group_service.create_space(
        owner,
        {"title": "Shared translation", "description": "Requester-funded"},
        "shared-translation-space",
    )["space"]["id"]
    app.state.group_service.add_member(
        owner,
        space_id,
        {
            "principal_type": recipient.principal_type,
            "principal_id": recipient.principal_id,
            "principal_user_id": recipient.principal_user_id,
            "display_name": recipient.display_name,
            "role": "member",
        },
    )
    for actor in (owner, recipient):
        app.state.group_translation_service.update_profile(
            actor,
            space_id,
            {
                "spoken_language": "vi",
                "preferred_output_language": "en",
                "auto_translate_enabled": True,
                "chat_auto_translate_enabled": False,
                "auto_read_enabled": False,
                "show_original_enabled": True,
            },
        )
        app.state.group_translation_service.update_consent(
            actor,
            space_id,
            "granted",
            app.state.settings.group_translation_policy_version,
        )
    return owner, recipient, space_id


def _message(
    app,
    actor,
    space_id: str,
    suffix: str,
    *,
    content: str | None = None,
) -> str:
    return app.state.group_service.create_message(
        actor,
        space_id,
        {
            "content": content or f"Nội dung cần dịch {suffix}",
            "content_type": "text",
            "client_message_id": f"shared-message-{suffix}",
            "source_language": "vi",
        },
        f"shared-message-{suffix}",
    )["message"]["id"]


def test_concurrent_same_target_uses_one_provider_call_and_one_payer(tmp_path):
    app = _native_app(
        tmp_path,
        group_translation_enabled=True,
        openai_api_key="render-server-key-never-sent-to-browser",
    )
    provider = FakeTextProvider("Shared result", delay_seconds=0.1)
    app.state.group_chat_translation_service.provider = provider
    owner, recipient, space_id = _seed_shared_translation(app)
    message_id = _message(app, owner, space_id, "concurrent")

    async def request_together():
        return await asyncio.gather(
            app.state.group_chat_translation_service.translate(
                owner, space_id, message_id, "shared-owner-request"
            ),
            app.state.group_chat_translation_service.translate(
                recipient, space_id, message_id, "shared-recipient-request"
            ),
        )

    results = asyncio.run(request_together())
    assert len(provider.calls) == 1
    assert results[0]["translation"]["id"] == results[1]["translation"]["id"]
    assert {result["idempotent"] for result in results} == {False, True}

    with app.state.database.session() as db:
        variants = list(db.scalars(select(GroupChatTranslation)).all())
        requests = list(db.scalars(select(GroupChatTranslationRequest)).all())
        ledgers = list(db.scalars(select(GroupChatTranslationCostLedger)).all())
        assert len(variants) == 1
        assert variants[0].status == "final"
        assert len(requests) == 2
        assert sorted(item.cost_state for item in requests) == ["reuse", "settled"]
        payer = next(item for item in requests if item.cost_state == "settled")
        assert variants[0].cost_owner_membership_id == payer.requester_membership_id
        assert sum(item.settled_variant_units for item in requests) == 1
        assert len(ledgers) == 1
        assert ledgers[0].reserved_variant_units == 0
        assert ledgers[0].settled_variant_units == 1


def test_existing_shared_variant_reuse_precedes_requester_quota_check(tmp_path):
    app = _native_app(
        tmp_path,
        group_translation_enabled=True,
        group_chat_translation_monthly_variant_limit=1,
        openai_api_key="render-server-key-never-sent-to-browser",
    )
    provider = FakeTextProvider("Shared result")
    app.state.group_chat_translation_service.provider = provider
    owner, recipient, space_id = _seed_shared_translation(app)
    shared_message = _message(app, owner, space_id, "shared")
    recipient_paid_message = _message(app, owner, space_id, "recipient-paid")
    blocked_message = _message(app, owner, space_id, "blocked")

    asyncio.run(
        app.state.group_chat_translation_service.translate(
            owner, space_id, shared_message, "owner-shared-variant"
        )
    )
    asyncio.run(
        app.state.group_chat_translation_service.translate(
            recipient, space_id, recipient_paid_message, "recipient-paid-variant"
        )
    )
    reused = asyncio.run(
        app.state.group_chat_translation_service.translate(
            recipient, space_id, shared_message, "recipient-reuses-shared"
        )
    )
    assert reused["translation"]["state"] == "FINAL"
    assert reused["idempotent"] is True
    assert len(provider.calls) == 2
    with app.state.database.session() as db:
        reuse_request = db.scalar(
            select(GroupChatTranslationRequest).where(
                GroupChatTranslationRequest.idempotency_key
                == "recipient-reuses-shared"
            )
        )
        assert reuse_request is not None
        assert reuse_request.cost_state == "reuse"
        assert reuse_request.reserved_variant_units == 0
        assert reuse_request.settled_variant_units == 0
        assert reuse_request.cost_ledger_id is None

    with pytest.raises(GroupServiceError) as denied:
        asyncio.run(
            app.state.group_chat_translation_service.translate(
                recipient, space_id, blocked_message, "recipient-over-quota"
            )
        )
    assert getattr(denied.value, "code", "") == "group_chat_translation_quota_exceeded"
    assert getattr(denied.value, "status_code", 0) == 429
    assert len(provider.calls) == 2


def test_shared_variant_identity_is_message_fingerprint_and_target_not_recipient(
    tmp_path,
):
    app = _native_app(
        tmp_path,
        group_translation_enabled=True,
        openai_api_key="render-server-key-never-sent-to-browser",
    )
    provider = FakeTextProvider("Shared result")
    app.state.group_chat_translation_service.provider = provider
    owner, recipient, space_id = _seed_shared_translation(app)
    identical_content = "Cùng nội dung nhưng là hai tin nhắn độc lập"
    first_message = _message(
        app, owner, space_id, "identity-first", content=identical_content
    )
    second_message = _message(
        app, owner, space_id, "identity-second", content=identical_content
    )

    asyncio.run(
        app.state.group_chat_translation_service.translate(
            owner, space_id, first_message, "identity-first-en"
        )
    )
    asyncio.run(
        app.state.group_chat_translation_service.translate(
            owner, space_id, second_message, "identity-second-en"
        )
    )
    app.state.group_translation_service.update_profile(
        recipient,
        space_id,
        {
            "spoken_language": "vi",
            "preferred_output_language": "zh-TW",
            "auto_translate_enabled": True,
            "chat_auto_translate_enabled": False,
            "auto_read_enabled": False,
            "show_original_enabled": True,
        },
    )
    asyncio.run(
        app.state.group_chat_translation_service.translate(
            recipient, space_id, first_message, "identity-first-zh-tw"
        )
    )

    assert len(provider.calls) == 3
    assert [call["target_language"] for call in provider.calls] == [
        "en",
        "en",
        "zh-TW",
    ]
    shared_constraint = next(
        constraint
        for constraint in GroupChatTranslation.__table__.constraints
        if constraint.name == "uq_group_chat_translation_shared_variant"
    )
    assert tuple(column.name for column in shared_constraint.columns) == (
        "message_id",
        "message_fingerprint",
        "target_language",
    )
    with app.state.database.session() as db:
        variants = list(db.scalars(select(GroupChatTranslation)).all())
        assert len(variants) == 3
        assert {
            (item.message_id, item.message_fingerprint, item.target_language)
            for item in variants
        } == {
            (first_message, variants[0].message_fingerprint, "en"),
            (second_message, variants[0].message_fingerprint, "en"),
            (first_message, variants[0].message_fingerprint, "zh-TW"),
        }


def test_source_history_and_profile_opt_in_do_not_precompute_chat_translation(tmp_path):
    app = _native_app(
        tmp_path,
        group_translation_enabled=True,
        openai_api_key="render-server-key-never-sent-to-browser",
    )
    provider = FakeTextProvider("Must not be created")
    app.state.group_chat_translation_service.provider = provider
    owner, recipient, space_id = _seed_shared_translation(app)
    message_id = _message(app, owner, space_id, "source-history-only")
    app.state.group_translation_service.update_profile(
        recipient,
        space_id,
        {
            "spoken_language": "vi",
            "preferred_output_language": "en",
            "auto_translate_enabled": True,
            "chat_auto_translate_enabled": True,
            "auto_read_enabled": False,
            "show_original_enabled": True,
        },
    )

    history = app.state.group_chat_translation_service.history(recipient, space_id, 100)

    assert history == []
    assert provider.calls == []
    with app.state.database.session() as db:
        assert list(db.scalars(select(GroupChatTranslation)).all()) == []
    profile = app.state.group_translation_service.profile(recipient, space_id)
    assert profile["chat_auto_translate_enabled"] is True
    assert profile["auto_read_enabled"] is False
    assert message_id


def test_message_edit_creates_a_new_shared_fingerprint_variant(tmp_path):
    app = _native_app(
        tmp_path,
        group_translation_enabled=True,
        openai_api_key="render-server-key-never-sent-to-browser",
    )
    provider = FakeTextProvider("Translated result")
    app.state.group_chat_translation_service.provider = provider
    owner, _recipient, space_id = _seed_shared_translation(app)
    message_id = _message(app, owner, space_id, "before-edit")

    first = asyncio.run(
        app.state.group_chat_translation_service.translate(
            owner, space_id, message_id, "translation-before-edit"
        )
    )
    app.state.group_service.update_message(
        owner,
        space_id,
        message_id,
        "Nội dung đã sửa cần một fingerprint mới",
    )
    second = asyncio.run(
        app.state.group_chat_translation_service.translate(
            owner, space_id, message_id, "translation-after-edit"
        )
    )

    assert first["translation"]["id"] != second["translation"]["id"]
    assert len(provider.calls) == 2
    history = app.state.group_chat_translation_service.history(owner, space_id, 10)
    assert [item["id"] for item in history] == [second["translation"]["id"]]


def test_chat_provider_failure_does_not_break_original_chat_and_can_retry(tmp_path):
    app, session, provider = _translation_runtime(tmp_path, "Recovered translation")
    provider.failure_code = "group_translation_provider_unavailable"
    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, session.session_id)
        space_id, message_id = _create_space_message_and_preferences(
            client,
            source_language="vi",
            target_language="en",
            original_text="Tin nhắn gốc vẫn phải hoạt động",
        )
        failed = client.post(
            f"/api/group/spaces/{space_id}/messages/{message_id}/translation",
            headers={"Origin": PUBLIC_ORIGIN, "Idempotency-Key": "chat-translation-fail-1"},
        )
        assert failed.status_code == 503
        assert failed.json()["detail"] == "group_translation_provider_unavailable"

        with app.state.database.session() as db:
            ledger = db.scalar(select(GroupChatTranslationCostLedger))
            request_row = db.scalar(select(GroupChatTranslationRequest))
            variant = db.scalar(select(GroupChatTranslation))
            assert ledger is not None
            assert ledger.reserved_variant_units == 0
            assert ledger.settled_variant_units == 0
            assert request_row.cost_state == "released"
            assert variant.cost_state == "released"

        messages = client.get(f"/api/group/spaces/{space_id}/messages?limit=10")
        assert messages.status_code == 200
        assert messages.json()["messages"][0]["content"] == "Tin nhắn gốc vẫn phải hoạt động"

        provider.failure_code = ""
        retried = client.post(
            f"/api/group/spaces/{space_id}/messages/{message_id}/translation",
            headers={"Origin": PUBLIC_ORIGIN, "Idempotency-Key": "chat-translation-retry-1"},
        )
        assert retried.status_code == 200
        assert retried.json()["translation"]["state"] == "FINAL"
        assert len(provider.calls) == 2

        with app.state.database.session() as db:
            ledger = db.scalar(select(GroupChatTranslationCostLedger))
            assert ledger.reserved_variant_units == 0
            assert ledger.settled_variant_units == 1


def test_cancelled_provider_releases_requester_quota(tmp_path):
    app = _native_app(
        tmp_path,
        group_translation_enabled=True,
        openai_api_key="render-server-key-never-sent-to-browser",
    )
    owner, _recipient, space_id = _seed_shared_translation(app)
    message_id = _message(app, owner, space_id, "cancelled-provider")

    class CancellingProvider:
        async def translate_text(self, **_values):
            raise asyncio.CancelledError

    app.state.group_chat_translation_service.provider = CancellingProvider()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            app.state.group_chat_translation_service.translate(
                owner, space_id, message_id, "cancelled-provider-request"
            )
        )

    with app.state.database.session() as db:
        ledger = db.scalar(select(GroupChatTranslationCostLedger))
        request_row = db.scalar(select(GroupChatTranslationRequest))
        variant = db.scalar(select(GroupChatTranslation))
        assert ledger is not None
        assert ledger.reserved_variant_units == 0
        assert ledger.settled_variant_units == 0
        assert request_row.cost_state == "released"
        assert request_row.reserved_variant_units == 0
        assert variant.status == "failed"
        assert variant.cost_state == "released"
        assert variant.failure_code == "group_translation_provider_cancelled"


def test_expired_reservation_is_reclaimed_before_next_quota_check(tmp_path):
    app = _native_app(
        tmp_path,
        group_translation_enabled=True,
        group_chat_translation_monthly_variant_limit=1,
        openai_api_key="render-server-key-never-sent-to-browser",
    )
    provider = FakeTextProvider("Recovered after expired lease")
    app.state.group_chat_translation_service.provider = provider
    owner, _recipient, space_id = _seed_shared_translation(app)
    abandoned_message_id = _message(app, owner, space_id, "abandoned-lease")
    next_message_id = _message(app, owner, space_id, "after-abandoned-lease")

    abandoned = app.state.group_chat_translation_service._prepare(
        owner,
        space_id,
        abandoned_message_id,
        "abandoned-lease-request",
    )
    assert abandoned["start_provider"] is True
    with app.state.database.session() as db:
        with db.begin():
            variant = db.get(GroupChatTranslation, abandoned["item"].id)
            variant.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    translated = asyncio.run(
        app.state.group_chat_translation_service.translate(
            owner,
            space_id,
            next_message_id,
            "request-after-expired-lease",
        )
    )
    assert translated["translation"]["state"] == "FINAL"
    assert len(provider.calls) == 1

    with app.state.database.session() as db:
        ledger = db.scalar(select(GroupChatTranslationCostLedger))
        abandoned_variant = db.get(GroupChatTranslation, abandoned["item"].id)
        abandoned_request = db.scalar(
            select(GroupChatTranslationRequest).where(
                GroupChatTranslationRequest.translation_id == abandoned_variant.id
            )
        )
        assert ledger.reserved_variant_units == 0
        assert ledger.settled_variant_units == 1
        assert abandoned_variant.status == "failed"
        assert abandoned_variant.failure_code == "group_translation_reservation_expired"
        assert abandoned_request.cost_state == "released"
        assert abandoned_request.reserved_variant_units == 0


def test_settled_cost_owner_and_request_survive_membership_deletion(tmp_path):
    app = _native_app(
        tmp_path,
        group_translation_enabled=True,
        openai_api_key="render-server-key-never-sent-to-browser",
    )
    app.state.group_chat_translation_service.provider = FakeTextProvider("Durable cost")
    owner, recipient, space_id = _seed_shared_translation(app)
    message_id = _message(app, owner, space_id, "durable-cost-owner")
    translated = asyncio.run(
        app.state.group_chat_translation_service.translate(
            recipient, space_id, message_id, "durable-cost-owner-request"
        )
    )
    translation_id = translated["translation"]["id"]

    with app.state.database.session() as db:
        with db.begin():
            membership = db.scalar(
                select(GroupMembership).where(
                    GroupMembership.space_id == space_id,
                    GroupMembership.principal_id == recipient.principal_id,
                    GroupMembership.principal_user_id == recipient.principal_user_id,
                )
            )
            payer_membership_id = membership.id
            db.delete(membership)

    with app.state.database.session() as db:
        variant = db.get(GroupChatTranslation, translation_id)
        request_row = db.scalar(
            select(GroupChatTranslationRequest).where(
                GroupChatTranslationRequest.translation_id == translation_id
            )
        )
        ledger = db.scalar(select(GroupChatTranslationCostLedger))
        assert variant is not None
        assert variant.cost_owner_membership_id == payer_membership_id
        assert request_row is not None
        assert request_row.requester_membership_id == payer_membership_id
        assert request_row.cost_state == "settled"
        assert ledger.settled_variant_units == 1


def test_chat_translation_requires_current_consent_before_provider_execution(tmp_path):
    app, session, provider = _translation_runtime(tmp_path, "Should not run")
    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, session.session_id)
        space = client.post(
            "/api/group/spaces",
            json={"title": "Consent QA", "description": ""},
            headers={"Origin": PUBLIC_ORIGIN, "Idempotency-Key": "consent-space-0001"},
        )
        space_id = space.json()["space"]["id"]
        sent = client.post(
            f"/api/group/spaces/{space_id}/messages",
            json={
                "content": "Không gửi provider khi chưa đồng ý",
                "content_type": "text",
                "client_message_id": "consent-message-0001",
                "source_language": "vi",
            },
            headers={"Origin": PUBLIC_ORIGIN, "Idempotency-Key": "consent-message-0001"},
        )
        denied = client.post(
            f"/api/group/spaces/{space_id}/messages/{sent.json()['message']['id']}/translation",
            headers={"Origin": PUBLIC_ORIGIN, "Idempotency-Key": "consent-translation-1"},
        )
        assert denied.status_code == 409
        assert denied.json()["detail"] == "group_translation_consent_required"
        assert provider.calls == []
