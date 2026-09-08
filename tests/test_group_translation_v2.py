from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.group_translation.provider import GroupTranslationProviderError, TextTranslationResult, SpeechTranscriptionResult
from app.group_v3.service import GroupServiceError
from fastapi.testclient import TestClient

from app.models import GroupLanguageProfile, GroupMediaParticipant, GroupMediaSession, GroupMembership, GroupTranslationConsent, GroupTranslationSegment, GroupTranslationVariant, GroupSpace
from tests.test_group_v3_native import AI_ENTITLEMENT, PUBLIC_ORIGIN, SCOPES, _future, _handoff_payload, _native_app


@dataclass
class FakeV2Provider:
    calls: list[dict]
    stt_calls: int = 0
    fail_targets: set[str] | None = None

    async def translate_text(self, **values):
        self.calls.append(values)
        if self.fail_targets and values["target_language"] in self.fail_targets:
            raise GroupTranslationProviderError("provider_temporarily_unavailable")
        return TextTranslationResult(
            text=f"{values['target_language']}:{values['source_text']}", model="fake-v2", request_id="req-v2"
        )

    async def transcribe_audio(self, **_values):
        self.stt_calls += 1
        return SpeechTranscriptionResult(text="transcribed source", model="fake-stt", request_id="stt-v2")


def _runtime(tmp_path, runtime_kind="video", **overrides):
    app = _native_app(tmp_path, group_translation_enabled=True, openai_api_key="server-only", **overrides)
    provider = FakeV2Provider([])
    app.state.group_translation_service.provider = provider
    session = app.state.bff_session_store.create_group_session(
        principal=_handoff_payload(runtime_kind)["principal"], scope=SCOPES,
        expires_at=_future(), handoff_id="handoff-v2", surface=runtime_kind, entitlement=AI_ENTITLEMENT,
    )
    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, session.session_id)
        created = client.post("/api/group/spaces", json={"title": "Translation V2", "description": "QA"}, headers={"Origin": PUBLIC_ORIGIN, "Idempotency-Key": "space-v2-0001"})
        assert created.status_code == 201
        space_id = created.json()["space"]["id"]
    with app.state.database.session() as db:
        with db.begin():
            space = db.get(GroupSpace, space_id)
            owner = db.scalar(select(GroupMembership).where(GroupMembership.space_id == space.id, GroupMembership.role == "owner"))
            guest = GroupMembership(id=str(uuid4()), space_id=space.id, principal_type="member", principal_id="99", principal_user_id="99", display_name="Guest", role="member", status="active")
            db.add(guest)
            db.flush()
            db.add_all([
                GroupLanguageProfile(id=str(uuid4()), space_id=space.id, membership_id=owner.id, spoken_language="vi", preferred_output_language="en", auto_translate_enabled=1, auto_read_enabled=0, show_original_enabled=1),
                GroupLanguageProfile(id=str(uuid4()), space_id=space.id, membership_id=guest.id, spoken_language="en", preferred_output_language="zh-TW", auto_translate_enabled=1, auto_read_enabled=0, show_original_enabled=1),
            ])
            media = GroupMediaSession(id=str(uuid4()), space_id=space.id, media_kind="audio" if runtime_kind == "call" else "video", title="V2", initiated_by_membership_id=owner.id, livekit_room_name="room-" + uuid4().hex, status="active")
            db.add(media)
            db.flush()
            db.add_all([
                GroupMediaParticipant(id=str(uuid4()), session_id=media.id, membership_id=owner.id, principal_type="member", principal_id="42", principal_user_id="42", display_name="Nguyen Minh", livekit_identity="owner", invite_status="joined", joined_at=datetime.now(timezone.utc)),
                GroupMediaParticipant(id=str(uuid4()), session_id=media.id, membership_id=guest.id, principal_type="member", principal_id="99", principal_user_id="99", display_name="Guest", livekit_identity="guest", invite_status="joined", joined_at=datetime.now(timezone.utc)),
            ])
            space_id, runtime_id = space.id, media.id
    return app, session, provider, space_id, runtime_id


@pytest.mark.parametrize("runtime_kind", ["call", "video"])
@pytest.mark.anyio
async def test_v2_text_dedupes_targets_and_projects_only_recipient_language(
    tmp_path, runtime_kind
):
    app, session, provider, space_id, runtime_id = _runtime(
        tmp_path, runtime_kind=runtime_kind
    )
    actor = __import__("app.group_v3.auth", fromlist=["GroupActor"]).GroupActor("member", "42", "42", "Nguyen Minh", "vi", frozenset(SCOPES), "h", runtime_kind, AI_ENTITLEMENT)
    first = await app.state.group_translation_service.submit_text(actor, space_id, {"runtime_kind": runtime_kind, "runtime_id": runtime_id, "client_segment_id": f"segment-v2-{runtime_kind}-0001", "source_language": "vi", "source_text": "Xin chao"})
    repeated = await app.state.group_translation_service.submit_text(actor, space_id, {"runtime_kind": runtime_kind, "runtime_id": runtime_id, "client_segment_id": f"segment-v2-{runtime_kind}-0001", "source_language": "vi", "source_text": "Xin chao"})
    assert first["state"] == "FINAL" and first["translated_text"] == "en:Xin chao"
    assert repeated["id"] == first["id"]
    assert len(provider.calls) == 2
    assert all(call["principal_id"] == actor.key for call in provider.calls)
    with app.state.database.session() as db:
        assert db.scalar(select(GroupTranslationSegment).where(GroupTranslationSegment.id == first["id"])) is not None
        assert len(list(db.scalars(select(GroupTranslationVariant).where(GroupTranslationVariant.segment_id == first["id"])).all())) == 2


@pytest.mark.anyio
async def test_v2_partial_variant_can_retry_without_retranscribing_source(tmp_path):
    app, _session, provider, space_id, runtime_id = _runtime(tmp_path)
    provider.fail_targets = {"zh-TW"}
    actor = __import__("app.group_v3.auth", fromlist=["GroupActor"]).GroupActor("member", "42", "42", "Nguyen Minh", "vi", frozenset(SCOPES), "h", "video", AI_ENTITLEMENT)
    result = await app.state.group_translation_service.submit_text(actor, space_id, {"runtime_kind": "video", "runtime_id": runtime_id, "client_segment_id": "segment-v2-0002", "source_language": "vi", "source_text": "Xin chao"})
    assert result["state"] in {"FINAL", "PARTIAL", "FAILED"}
    provider.fail_targets = set()
    retried = await app.state.group_translation_service.retry_variant(actor, space_id, result["id"], "zh-TW")
    assert retried["translated_text"] == "zh-TW:Xin chao"
    assert len(provider.calls) >= 3


@pytest.mark.anyio
async def test_v2_voice_calls_stt_once_and_reuses_segment(tmp_path):
    app, _session, provider, space_id, runtime_id = _runtime(tmp_path)
    actor = __import__("app.group_v3.auth", fromlist=["GroupActor"]).GroupActor("member", "42", "42", "Nguyen Minh", "vi", frozenset(SCOPES), "h", "video", AI_ENTITLEMENT)
    with app.state.database.session() as db:
        with db.begin():
            from app.models import GroupTranslationConsent
            membership = db.scalar(select(GroupMembership).where(GroupMembership.space_id == space_id, GroupMembership.principal_id == "42"))
            from datetime import datetime, timezone
            db.add(GroupTranslationConsent(id=str(uuid4()), space_id=space_id, membership_id=membership.id, status="granted", policy_version=app.state.settings.group_translation_policy_version, decided_at=datetime.now(timezone.utc)))
    values = {"runtime_kind": "video", "runtime_id": runtime_id, "client_segment_id": "segment-v2-voice1", "source_language": "vi"}
    first = await app.state.group_translation_service.submit_voice(actor, space_id, values, b"audio", "voice.webm", "audio/webm")
    second = await app.state.group_translation_service.submit_voice(actor, space_id, values, b"audio", "voice.webm", "audio/webm")
    assert first["source_text"] == "transcribed source" and second["id"] == first["id"]
    assert provider.stt_calls == 1


@pytest.mark.anyio
async def test_v2_missing_profile_uses_same_deterministic_fallback_for_routing_and_projection(tmp_path):
    app, _session, provider, space_id, runtime_id = _runtime(tmp_path)
    with app.state.database.session() as db:
        with db.begin():
            guest = db.scalar(select(GroupMembership).where(GroupMembership.space_id == space_id, GroupMembership.principal_id == "99"))
            profile = db.scalar(select(GroupLanguageProfile).where(GroupLanguageProfile.membership_id == guest.id))
            db.delete(profile)
    owner = __import__("app.group_v3.auth", fromlist=["GroupActor"]).GroupActor("member", "42", "42", "Nguyen Minh", "vi", frozenset(SCOPES), "h", "video", AI_ENTITLEMENT)
    submitted = await app.state.group_translation_service.submit_text(
        owner,
        space_id,
        {"runtime_kind": "video", "runtime_id": runtime_id, "client_segment_id": "segment-v2-missing", "source_language": "vi", "source_text": "Xin chao"},
    )
    assert submitted["projection"] == "author"
    source_variant = next(item for item in submitted["variants"] if item["target_language"] == "vi")
    assert source_variant["recipient_count"] == 1
    assert [call["target_language"] for call in provider.calls] == ["en"]

    guest_actor = __import__("app.group_v3.auth", fromlist=["GroupActor"]).GroupActor("member", "99", "99", "Guest", "zh-TW", frozenset(SCOPES), "h", "video", AI_ENTITLEMENT)
    received = app.state.group_translation_service.v2_history(guest_actor, space_id, "video", runtime_id, 10)
    assert received[0]["projection"] == "recipient"
    assert received[0]["profile_source"] == "fallback"
    assert received[0]["display_language"] == "vi"
    assert received[0]["translated_text"] == "Xin chao"


@pytest.mark.anyio
async def test_v2_rejects_a_second_idempotency_identity(tmp_path):
    app, _session, _provider, space_id, runtime_id = _runtime(tmp_path)
    actor = __import__("app.group_v3.auth", fromlist=["GroupActor"]).GroupActor("member", "42", "42", "Nguyen Minh", "vi", frozenset(SCOPES), "h", "video", AI_ENTITLEMENT)
    with pytest.raises(GroupServiceError, match="group_translation_idempotency_mismatch"):
        await app.state.group_translation_service.submit_text(
            actor,
            space_id,
            {"runtime_kind": "video", "runtime_id": runtime_id, "client_segment_id": "segment-v2-idem", "source_language": "vi", "source_text": "Xin chao"},
            idempotency_key="another-idempotency-key",
        )


@pytest.mark.anyio
async def test_v2_abc_routes_preferences_even_with_legacy_auto_disabled(tmp_path):
    app, _, provider, space_id, runtime_id = _runtime(tmp_path)
    from app.group_v3.auth import GroupActor
    owner_actor = GroupActor("member", "42", "42", "A", "vi", frozenset(SCOPES), "h", "video", AI_ENTITLEMENT)
    with app.state.database.session() as db, db.begin():
        profiles = list(db.scalars(select(GroupLanguageProfile).where(GroupLanguageProfile.space_id == space_id)))
        for profile in profiles:
            profile.auto_translate_enabled = 0
        third = GroupMembership(id=str(uuid4()), space_id=space_id, principal_type="member", principal_id="100",
            principal_user_id="100", display_name="C", role="member", status="active")
        db.add(third)
        db.flush()
        db.add(GroupLanguageProfile(id=str(uuid4()), space_id=space_id, membership_id=third.id,
            spoken_language="vi", preferred_output_language="vi", auto_translate_enabled=0,
            auto_read_enabled=0, show_original_enabled=1))
        db.add(GroupMediaParticipant(id=str(uuid4()), session_id=runtime_id, membership_id=third.id,
            principal_type="member", principal_id="100", principal_user_id="100", display_name="C",
            livekit_identity="third", invite_status="joined", joined_at=datetime.now(timezone.utc)))
    result = await app.state.group_translation_service.submit_text(owner_actor, space_id, {
        "runtime_kind": "video", "runtime_id": runtime_id, "client_segment_id": "abc-preference-0001",
        "source_language": "vi", "source_text": "Xin chào"})
    assert sorted(call["target_language"] for call in provider.calls) == ["en", "zh-TW"]
    # Sender preview is not counted as a delivered recipient.
    assert {v["target_language"]: v["recipient_count"] for v in result["variants"]} == {"vi": 1, "en": 0, "zh-TW": 1}
    for principal, target in [("99", "zh-TW"), ("100", "vi")]:
        actor = GroupActor("member", principal, principal, "Recipient", "en", frozenset(SCOPES), "h", "video", AI_ENTITLEMENT)
        item = app.state.group_translation_service.v2_history(actor, space_id, "video", runtime_id, 10)[0]
        assert item["display_language"] == target and item["state"] == "FINAL"
        assert item["translated_text"] == ("Xin chào" if target == "vi" else "zh-TW:Xin chào")


@pytest.mark.anyio
async def test_v2_voice_failed_variant_retry_does_not_repeat_stt(tmp_path):
    app, _, provider, space_id, runtime_id = _runtime(tmp_path)
    from app.group_v3.auth import GroupActor
    from datetime import datetime, timezone
    actor = GroupActor("member", "42", "42", "A", "vi", frozenset(SCOPES), "h", "video", AI_ENTITLEMENT)
    with app.state.database.session() as db, db.begin():
        membership = db.scalar(select(GroupMembership).where(GroupMembership.space_id == space_id, GroupMembership.principal_id == "42"))
        db.add(GroupTranslationConsent(id=str(uuid4()), space_id=space_id, membership_id=membership.id,
            status="granted", policy_version=app.state.settings.group_translation_policy_version,
            decided_at=datetime.now(timezone.utc)))
    provider.fail_targets = {"zh-TW"}
    result = await app.state.group_translation_service.submit_voice(actor, space_id, {
        "runtime_kind": "video", "runtime_id": runtime_id, "client_segment_id": "voice-retry-0001",
        "source_language": "vi", "duration_seconds": 2.5}, b"audio fixture", "voice.m4a", "audio/mp4")
    assert result["state"] == "PARTIAL" and result["source_text"] == "transcribed source"
    provider.fail_targets = set()
    await app.state.group_translation_service.retry_variant(actor, space_id, result["id"], "zh-TW")
    assert provider.stt_calls == 1
    assert [c["target_language"] for c in provider.calls].count("en") == 1
    assert [c["target_language"] for c in provider.calls].count("zh-TW") == 2


@pytest.mark.anyio
async def test_v2_rejects_empty_voice_without_provider_call(tmp_path):
    app, _, provider, space_id, runtime_id = _runtime(tmp_path)
    from app.group_v3.auth import GroupActor
    actor = GroupActor("member", "42", "42", "A", "vi", frozenset(SCOPES), "h", "video", AI_ENTITLEMENT)
    with pytest.raises(GroupServiceError, match="group_translation_audio_invalid"):
        await app.state.group_translation_service.submit_voice(actor, space_id, {
            "runtime_kind": "video", "runtime_id": runtime_id, "client_segment_id": "voice-empty-0001",
            "source_language": "vi"}, b"", "voice.webm", "audio/webm")
    assert provider.stt_calls == 0
