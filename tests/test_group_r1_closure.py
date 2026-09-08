"""R1 critical domain closure. All providers and floor transport are local doubles."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import asyncio
import json
import tempfile

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import Settings
from app.group_translation.provider import OpenAIGroupTranslationProvider, SpeechTranscriptionResult
from app.group_v3.auth import GroupActor
from app.group_v3.service import GroupServiceError
from app.group_v3.translation_schemas import LanguageProfileUpdate, TranslationSegmentTextCreate
from app.models import (GroupLanguageProfile, GroupMediaParticipant, GroupMediaSession, GroupMembership,
    GroupRadioBurst, GroupRadioProcessingJob, GroupRadioSession, GroupTranslationConsent,
    GroupTranslationSegment, GroupTranslationVariant)
from tests.test_group_translation_v2 import _runtime, FakeV2Provider
from tests.test_group_radio_floor_v3 import FakeAsyncRedis
from tests.test_group_v3_native import SCOPES, AI_ENTITLEMENT, PUBLIC_ORIGIN

def actor(principal="42"):
    return GroupActor("member", principal, principal, "QA " + principal, "vi", frozenset(SCOPES), "h", "video", AI_ENTITLEMENT)

def consent(app, space_id):
    with app.state.database.session() as db, db.begin():
        for member in db.scalars(select(GroupMembership).where(GroupMembership.space_id == space_id)):
            db.add(GroupTranslationConsent(id=str(uuid4()), space_id=space_id, membership_id=member.id,
                status="granted", policy_version=app.state.settings.group_translation_policy_version,
                decided_at=datetime.now(timezone.utc)))

class Detector(FakeV2Provider):
    resolved = "vi"
    detections = 0
    async def detect_supported_language(self, text, principal_id, idempotency_key):
        self.detections += 1
        return self.resolved


def add_member(app, space_id, runtime_id, principal, target, *, participate=True):
    with app.state.database.session() as db, db.begin():
        member = GroupMembership(
            id=str(uuid4()), space_id=space_id, principal_type="member",
            principal_id=principal, principal_user_id=principal,
            display_name="QA " + principal, role="member", status="active",
        )
        db.add(member)
        db.flush()
        db.add(GroupLanguageProfile(
            id=str(uuid4()), space_id=space_id, membership_id=member.id,
            spoken_language=target, preferred_output_language=target,
            auto_translate_enabled=1, auto_read_enabled=1,
            show_original_enabled=1,
        ))
        if participate:
            db.add(GroupMediaParticipant(
                id=str(uuid4()), session_id=runtime_id,
                membership_id=member.id, principal_type="member",
                principal_id=principal, principal_user_id=principal,
                display_name=member.display_name,
                livekit_identity="member-" + principal,
                invite_status="joined", joined_at=datetime.now(timezone.utc),
            ))
        return member.id

@pytest.mark.parametrize("language", ["auto", "vi", "en", "zh-TW"])
def test_auto_is_request_mode_not_profile_language(language):
    request = TranslationSegmentTextCreate(runtime_kind="video", runtime_id=str(uuid4()),
        client_segment_id="r1-language-0001", source_language=language, source_text="Test")
    assert request.source_language == language
    if language == "auto":
        with pytest.raises(ValidationError):
            LanguageProfileUpdate(spoken_language="auto", preferred_output_language="en")

@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["text", "voice"])
@pytest.mark.parametrize("resolved", ["vi", "en", "zh-TW", "unsupported"])
async def test_detect_resolves_before_persist_and_rejects_unsupported(tmp_path, kind, resolved):
    app, _, _, space, runtime = _runtime(tmp_path)
    consent(app, space)
    provider = Detector([])
    provider.resolved = resolved
    service = app.state.group_translation_service
    service.provider = provider
    values = dict(runtime_kind="video", runtime_id=runtime, client_segment_id="r1-auto-0001",
        source_language="auto", source_text="Untrusted input", duration_seconds=2)
    async def submit():
        if kind == "voice":
            return await service.submit_voice(actor(), space, values, b"transient", "voice.m4a", "audio/mp4")
        return await service.submit_text(actor(), space, values)
    if resolved == "unsupported":
        with pytest.raises(GroupServiceError, match="group_translation_detected_language_unsupported"):
            await submit()
    else:
        result = await submit()
        repeated = await submit()
        assert result["source_language"] == resolved
        assert result["id"] == repeated["id"]
        assert provider.detections == 1
        assert provider.stt_calls == (1 if kind == "voice" else 0)
    with app.state.database.session() as db:
        rows = list(db.scalars(select(GroupTranslationSegment)))
        assert len(rows) == (0 if resolved == "unsupported" else 1)
        assert all(row.source_language in {"vi", "en", "zh-TW"} for row in rows)
        assert all(p.spoken_language != "auto" for p in db.scalars(select(GroupLanguageProfile)))

@pytest.mark.anyio
async def test_video_archive_ended_left_pagination_and_removed_membership(tmp_path):
    app, _, _, space, runtime = _runtime(tmp_path)
    service = app.state.group_translation_service
    for index in range(3):
        await service.submit_text(actor(), space, dict(runtime_kind="video", runtime_id=runtime,
            client_segment_id=f"r1-history-{index}", source_language="vi", source_text=f"Source {index}"))
    with app.state.database.session() as db, db.begin():
        db.get(GroupMediaSession, runtime).status = "ended"
        for participant in db.scalars(select(GroupMediaParticipant)):
            participant.invite_status = "left"
    first = service.v2_history(actor("99"), space, "video", runtime, 2)
    second = service.v2_history(actor("99"), space, None, None, 2, first[-1]["id"])
    assert len(first) == 2 and len(second) == 1
    assert not {x["id"] for x in first} & {x["id"] for x in second}
    assert all(x["speaker_display_name"] and x["source_text"] and x["translated_text"] and x["created_at"] for x in first)
    with pytest.raises(GroupServiceError, match="not_active"):
        await service.submit_text(actor(), space, dict(runtime_kind="video", runtime_id=runtime,
            client_segment_id="r1-history-late", source_language="vi", source_text="Denied"))
    with app.state.database.session() as db, db.begin():
        db.scalar(select(GroupMembership).where(GroupMembership.principal_id == "99")).status = "removed"
    with pytest.raises(GroupServiceError):
        service.v2_history(actor("99"), space, "video", runtime, 10)


@pytest.mark.anyio
async def test_terminal_recipient_projection_never_reports_final_without_text(tmp_path):
    app, _, _, space, runtime = _runtime(tmp_path)
    service = app.state.group_translation_service
    result = await service.submit_text(actor(), space, dict(
        runtime_kind="video", runtime_id=runtime,
        client_segment_id="r1-missing-recipient-variant",
        source_language="vi", source_text="Source requiring translation",
    ))
    with app.state.database.session() as db, db.begin():
        variant = db.scalar(select(GroupTranslationVariant).where(
            GroupTranslationVariant.segment_id == result["id"],
            GroupTranslationVariant.target_language == "zh-TW",
        ))
        assert variant is not None
        db.delete(variant)
    projected = service.v2_history(actor("99"), space, "video", runtime, 10)[0]
    assert projected["translated_text"] is None
    assert projected["state"] == "FAILED"
    assert projected["failure_code"] == "group_translation_variant_missing"


@pytest.mark.anyio
async def test_five_member_room_creates_one_shared_variant_per_target_language(tmp_path):
    app, _, provider, space, runtime = _runtime(tmp_path)
    with app.state.database.session() as db, db.begin():
        owner = db.scalar(select(GroupMembership).where(
            GroupMembership.space_id == space, GroupMembership.principal_id == "42"))
        db.scalar(select(GroupLanguageProfile).where(
            GroupLanguageProfile.membership_id == owner.id)).preferred_output_language = "vi"
    add_member(app, space, runtime, "100", "zh-TW")
    add_member(app, space, runtime, "101", "en")
    add_member(app, space, runtime, "102", "en")
    result = await app.state.group_translation_service.submit_text(actor(), space, dict(
        runtime_kind="video", runtime_id=runtime,
        client_segment_id="r1-five-member-shared", source_language="vi",
        source_text="Xin chào cả nhóm",
    ))
    assert sorted(call["target_language"] for call in provider.calls) == ["en", "zh-TW"]
    assert all(call["principal_id"] == "member:42:42" for call in provider.calls)
    variants = {item["target_language"]: item for item in result["variants"]}
    assert variants["zh-TW"]["recipient_count"] == 2
    assert variants["en"]["recipient_count"] == 2
    with app.state.database.session() as db:
        stored = list(db.scalars(select(GroupTranslationVariant).where(
            GroupTranslationVariant.segment_id == result["id"])).all())
        assert len(stored) == 2


@pytest.mark.anyio
async def test_late_join_source_history_is_visible_without_automatic_translation(tmp_path):
    app, _, provider, space, runtime = _runtime(tmp_path)
    result = await app.state.group_translation_service.submit_text(actor(), space, dict(
        runtime_kind="video", runtime_id=runtime,
        client_segment_id="r1-late-source-visible", source_language="vi",
        source_text="Nguồn lịch sử",
    ))
    calls_before_join = len(provider.calls)
    add_member(app, space, runtime, "late", "en", participate=False)
    late_actor = actor("late")
    history = app.state.group_translation_service.v2_history(
        late_actor, space, None, None, 50)
    projected = next(item for item in history if item["id"] == result["id"])
    assert projected["source_text"] == "Nguồn lịch sử"
    assert len(provider.calls) == calls_before_join


@pytest.mark.anyio
async def test_historical_existing_variant_is_reused_at_zero_provider_cost(tmp_path):
    app, _, provider, space, runtime = _runtime(tmp_path)
    result = await app.state.group_translation_service.submit_text(actor(), space, dict(
        runtime_kind="video", runtime_id=runtime,
        client_segment_id="r1-history-reuse", source_language="vi",
        source_text="Dùng lại bản dịch",
    ))
    add_member(app, space, runtime, "late-reuse", "zh-TW", participate=False)
    calls_before = len(provider.calls)
    projected = await app.state.group_translation_service.retry_variant(
        actor("late-reuse"), space, result["id"], "zh-TW")
    assert projected["translated_text"] == "zh-TW:Dùng lại bản dịch"
    assert len(provider.calls) == calls_before


@pytest.mark.anyio
async def test_historical_same_language_projection_uses_zero_provider_work(tmp_path):
    app, _, provider, space, runtime = _runtime(tmp_path)
    result = await app.state.group_translation_service.submit_text(actor(), space, dict(
        runtime_kind="video", runtime_id=runtime,
        client_segment_id="r1-history-same-language", source_language="vi",
        source_text="Không cần dịch",
    ))
    add_member(app, space, runtime, "late-same", "vi", participate=False)
    calls_before = len(provider.calls)
    projected = await app.state.group_translation_service.retry_variant(
        actor("late-same"), space, result["id"], "vi")
    assert projected["translated_text"] == "Không cần dịch"
    assert projected["state"] == "FINAL"
    assert len(provider.calls) == calls_before


@pytest.mark.anyio
async def test_historical_missing_variant_is_created_once_and_charged_to_source_author(tmp_path):
    app, _, provider, space, runtime = _runtime(tmp_path)
    with app.state.database.session() as db, db.begin():
        for profile in db.scalars(select(GroupLanguageProfile).where(
                GroupLanguageProfile.space_id == space)):
            profile.preferred_output_language = "vi"
    result = await app.state.group_translation_service.submit_text(actor(), space, dict(
        runtime_kind="video", runtime_id=runtime,
        client_segment_id="r1-history-lazy", source_language="vi",
        source_text="Tạo khi được yêu cầu",
    ))
    assert provider.calls == []
    add_member(app, space, runtime, "late-lazy", "zh-TW", participate=False)
    before = app.state.group_translation_service.v2_history(
        actor("late-lazy"), space, None, None, 50)[0]
    assert before["source_text"] == "Tạo khi được yêu cầu"
    assert before["translated_text"] is None
    assert before["failure_code"] == "group_translation_variant_missing"
    projected = await app.state.group_translation_service.retry_variant(
        actor("late-lazy"), space, result["id"], "zh-TW")
    assert projected["translated_text"] == "zh-TW:Tạo khi được yêu cầu"
    assert len(provider.calls) == 1
    assert provider.calls[0]["principal_id"] == "member:42:42"
    assert provider.calls[0]["principal_id"] != actor("late-lazy").key


@pytest.mark.anyio
async def test_concurrent_historical_requests_coalesce_shared_variant_provider_work(tmp_path):
    app, _, provider, space, runtime = _runtime(tmp_path)
    with app.state.database.session() as db, db.begin():
        for profile in db.scalars(select(GroupLanguageProfile).where(
                GroupLanguageProfile.space_id == space)):
            profile.preferred_output_language = "vi"
    result = await app.state.group_translation_service.submit_text(actor(), space, dict(
        runtime_kind="video", runtime_id=runtime,
        client_segment_id="r1-history-concurrent", source_language="vi",
        source_text="Một shared variant",
    ))
    add_member(app, space, runtime, "late-a", "zh-TW", participate=False)
    add_member(app, space, runtime, "late-b", "zh-TW", participate=False)
    first, second = await asyncio.gather(
        app.state.group_translation_service.retry_variant(actor("late-a"), space, result["id"], "zh-TW"),
        app.state.group_translation_service.retry_variant(actor("late-b"), space, result["id"], "zh-TW"),
    )
    assert first["translated_text"] == second["translated_text"] == "zh-TW:Một shared variant"
    assert len(provider.calls) == 1
    with app.state.database.session() as db:
        variants = list(db.scalars(select(GroupTranslationVariant).where(
            GroupTranslationVariant.segment_id == result["id"],
            GroupTranslationVariant.target_language == "zh-TW",
        )).all())
        assert len(variants) == 1

class ProviderClient:
    output = '{"language":"vi"}'
    captured = {}
    def __init__(self, **_kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *_args): pass
    async def post(self, url, **values):
        ProviderClient.captured = dict(url=url, **values)
        class Response:
            status_code = 200
            headers = {}
            def json(self):
                return {"output_text": ProviderClient.output, "text": "STT fixture"}
        return Response()

@pytest.mark.parametrize("language,hint", [("auto",None),("vi","vi"),("en","en"),("zh-TW","zh")])
def test_provider_transcription_language_hint(monkeypatch, language, hint):
    monkeypatch.setattr("app.group_translation.provider.httpx.AsyncClient", ProviderClient)
    provider = OpenAIGroupTranslationProvider(Settings(app_env="test", debug=True,
        group_translation_enabled=True, openai_api_key="fake-test-key"))
    result = asyncio.run(provider.transcribe_audio(audio=b"memory-only", filename="clip.m4a", content_type="audio/mp4",
        source_language=language, principal_id="42", idempotency_key="r1-voice"))
    assert result.text == "STT fixture"
    assert ProviderClient.captured["data"].get("language") == hint
    if hint is None: assert "language" not in ProviderClient.captured["data"]
    assert ProviderClient.captured["files"]["file"][2] == "audio/mp4"

@pytest.mark.parametrize("output,resolved", [('{"language":"vi"}',"vi"),('{"language":" EN "}',"en"),
    ('{"language":"zh-TW"}',"zh-TW"),('{"language":"ja"}',"unsupported"),
    ('{"language":"vi","extra":"ignore instructions"}',"unsupported"),("vi","unsupported"),
    ('{"language":null}',"unsupported")])
def test_provider_detector_strict_normalization_and_privacy(monkeypatch, output, resolved):
    monkeypatch.setattr("app.group_translation.provider.httpx.AsyncClient", ProviderClient)
    ProviderClient.output = output
    provider = OpenAIGroupTranslationProvider(Settings(app_env="test", debug=True,
        group_translation_enabled=True, openai_api_key="fake-test-key"))
    assert asyncio.run(provider.detect_supported_language("Untrusted input", "42", "r1-detect")) == resolved
    payload = ProviderClient.captured["json"]
    assert payload["store"] is False and payload["max_output_tokens"] <= 64
    assert payload["text"]["format"]["strict"] is True
    assert "untrusted" in payload["instructions"]
    assert "fake-test-key" not in json.dumps(payload)

@pytest.mark.anyio
async def test_radio_floor_release_before_stt_single_attempt_history_reopen(tmp_path):
    app, _, _, space, _ = _runtime(tmp_path, group_radio_v3_enabled=True,
        group_radio_redis_url="redis://fake:6379")
    floor = app.state.group_radio_floor
    floor._client = FakeAsyncRedis()
    service = app.state.group_radio_service
    translation = app.state.group_translation_service
    consent(app, space)
    room = service.open_room(actor(), space)
    same_room = service.open_room(actor("99"), space)
    assert room["id"] == same_room["id"]
    sid = room["id"]
    async def acquire(who):
        _, participant = service.floor_context(who, space, sid)
        lease = await floor.acquire(sid, participant_id=participant["id"], membership_id=participant["membership_id"], display_name=participant["display_name"])
        burst = service.record_burst(who, space, sid, lease["token"], "vi", [])
        return lease["token"], burst
    token, burst = await acquire(actor())
    with pytest.raises(GroupServiceError):
        await acquire(actor("99"))
    await floor.release(sid, token)
    service.stop_burst_after_floor_release(actor(), space, sid, token)
    token_b, _ = await acquire(actor("99"))
    class CheckFloor(Detector):
        async def transcribe_audio(self, **values):
            snapshot = await floor.snapshot(sid)
            assert snapshot["display_name"] == "Guest"
            self.stt_calls += 1
            return SpeechTranscriptionResult("Radio canonical source", "fake", None)
    provider = CheckFloor([])
    translation.provider = provider
    # Legitimate leave after release must not abort asynchronous text finalization.
    service.leave(actor(), space, sid)
    result = await translation.submit_radio_voice(actor(), space, sid, burst["id"],
        {"source_language":"auto","duration_seconds":"2"}, b"transient-clip", "clip.m4a", "audio/mp4")
    repeated = await translation.submit_radio_voice(actor(), space, sid, burst["id"],
        {}, b"duplicate", "clip.m4a", "audio/mp4")
    assert result["id"] == repeated["id"] and provider.stt_calls == 1
    assert provider.calls and all(
        call["principal_id"] == actor().key for call in provider.calls
    )
    assert result["client_segment_id"] == burst["id"] and result["source_language"] == "vi"
    history = service.room_history(actor(), space, translation)
    final = next(x for x in history if x["id"] == burst["id"])
    assert final["state"] == "final" and final["segment"]["source_text"] == "Radio canonical source"
    assert final["speaker_display_name"] and final["started_at"] and final["stopped_at"]
    await floor.release(sid, token_b)
    service.stop_burst_after_floor_release(actor("99"), space, sid, token_b)
    assert service.open_room(actor(), space)["id"] == sid
    assert translation.v2_history(actor(), space, "radio", sid, 10)
    # The archive spans internal transport epochs.
    with app.state.database.session() as db, db.begin():
        db.get(GroupRadioSession, sid).status = "ended"
    assert service.open_room(actor(), space)["id"] != sid
    assert any(x["id"] == burst["id"] for x in service.room_history(actor(), space, translation))
    with app.state.database.session() as db:
        job = db.scalar(select(GroupRadioProcessingJob).where(GroupRadioProcessingJob.burst_id == burst["id"]))
        assert job.status == "completed"
        assert not any("audio" in c.name for model in [GroupRadioBurst, GroupTranslationSegment] for c in model.__table__.columns)

@pytest.mark.parametrize("device_lost", [False, True])
def test_radio_leave_endpoint_owned_floor_or_device_lost_never_traps(tmp_path, device_lost):
    app, session, _, space, _ = _runtime(tmp_path, group_radio_v3_enabled=True,
        group_radio_redis_url="redis://fake:6379")
    app.state.group_radio_floor._client = FakeAsyncRedis()
    headers = {"Origin":PUBLIC_ORIGIN}
    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, session.session_id)
        joined = client.post(f"/api/group/spaces/{space}/radio/room/join", headers=headers)
        assert joined.status_code == 200, joined.text
        sid = joined.json()["session"]["id"]
        base = f"/api/group/spaces/{space}/radio/sessions/{sid}"
        acquired = client.post(base+"/floor/acquire", headers=headers, json={"source_language":"vi","target_languages":[]})
        assert acquired.status_code == 201, acquired.text
        if device_lost:
            lost = client.post(base+"/floor/device-lost", headers=headers,
                json={"floor_token":acquired.json()["floor_token"]})
            assert lost.status_code == 200
        assert client.post(base+"/leave", headers=headers).status_code == 200
        assert client.post(base+"/leave", headers=headers).status_code == 200
        detail = client.get(base).json()
        assert detail["floor"] is None
        assert detail["session"]["participants"][0]["status"] == "left"

def test_multipart_clip_never_spools_to_disk_and_dedupes(tmp_path, monkeypatch):
    app, session, provider, space, runtime = _runtime(tmp_path)
    consent(app, space)
    def forbidden(*args, **kwargs): raise AssertionError("Audio must not be spooled")
    monkeypatch.setattr(tempfile, "TemporaryFile", forbidden)
    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", forbidden)
    # Over Starlette's ordinary 1 MiB spool threshold, below the bounded limit.
    with TestClient(app) as client:
        client.cookies.set(app.state.settings.guilua_session_cookie, session.session_id)
        for _ in range(2):
            response = client.post(f"/api/group/spaces/{space}/translation/segments/voice",
                headers={"Origin":PUBLIC_ORIGIN, "Idempotency-Key":"r1-memory-voice"},
                data=dict(runtime_kind="video",runtime_id=runtime,client_segment_id="r1-memory-voice",
                    source_language="vi",duration_seconds="2"),
                files={"audio":("clip.m4a", b"x"*(1024*1024+8), "audio/mp4")})
            assert response.status_code == 201, response.text
        assert provider.stt_calls == 1


@pytest.mark.anyio
async def test_radio_failed_claim_is_terminal_and_space_history_is_visible_to_member(tmp_path):
    app, _, _, space, _ = _runtime(tmp_path, group_radio_v3_enabled=True)
    service, translation = app.state.group_radio_service, app.state.group_translation_service
    consent(app, space)
    with app.state.database.session() as db:
        guest = db.scalar(select(GroupMembership).where(GroupMembership.principal_id == "99"))
        guest_id = guest.id
    room = service.create_session(actor(), space, {"participant_membership_ids":[guest_id]})
    sid = room["id"]
    burst = service.record_burst(actor(), space, sid, "unit-floor-token", "vi", [])
    with pytest.raises(GroupServiceError, match="burst_not_released"):
        await translation.submit_radio_voice(actor(), space, sid, burst["id"], {}, b"x", "v.webm", "audio/webm")
    service.stop_burst_after_floor_release(actor(), space, sid, "unit-floor-token")
    provider = Detector([])
    provider.resolved = "unsupported"
    translation.provider = provider
    with pytest.raises(GroupServiceError, match="detected_language_unsupported"):
        await translation.submit_radio_voice(actor(), space, sid, burst["id"], {"source_language":"auto"},
            b"x", "v.webm", "audio/webm")
    with pytest.raises(GroupServiceError, match="already_submitted"):
        await translation.submit_radio_voice(actor(), space, sid, burst["id"], {},
            b"x", "v.webm", "audio/webm")
    assert provider.stt_calls == 1
    with pytest.raises(GroupServiceError, match="participant_required"):
        translation.v2_history(actor("99"), space, "radio", sid, 10)
    guest_row = service.room_history(actor("99"), space, translation)[0]
    assert guest_row["state"] == "failed" and guest_row["segment"] is None
    row = service.room_history(actor(), space, translation)[0]
    assert row["state"] == "failed" and row["segment"] is None

def test_r1_static_no_audio_storage_and_protected_voice_button():
    root = Path(__file__).resolve().parents[1]
    recorder = (root/"app/static/group-v3/group_radio_recording.js").read_text(encoding="utf-8")
    assert "getUserMedia" not in recorder and "localStorage" not in recorder and "indexedDB" not in recorder
    assert "new window.MediaStream([track])" in recorder or "new MediaStream([track])" in recorder
    app = (root/"app/static/group-v3/group_v3_app.js").read_text(encoding="utf-8")
    stop = app[app.index("  async function stopRadio()"):app.index("  async function radioDeviceLost()")]
    assert "var clipPromise = window.GroupV3RadioRecording.stop(false);" in stop
    assert "await window.GroupV3RadioRecording.stop(false)" not in stop
    assert stop.index('"/floor/stop"') < stop.index("clipPromise.then")
    assert stop.index('"/floor/stop"') < stop.index("finalizeRadioClip(context, clip)")
    voice = (root/"app/static/group-v3/group_v3_translation.js").read_text(encoding="utf-8")
    assert 'source.value !== "auto"' in voice
    tts = (root/"app/static/group-v3/group_tts_manager.js").read_text(encoding="utf-8")
    assert "utterance.onstart" in tts and "utterance.onend" in tts and "utterance.onerror" in tts
    assert "voiceschanged" in tts and "startTimeoutMs" in tts
    assert "localStorage" not in tts and "indexedDB" not in tts
    template = (root/"app/templates/group_communication_v3.html").read_text(encoding="utf-8")
    assert "group_radio_recording.js" in template and "group_v3_room_closure.css" in template
    assert "group_tts_manager.js" in template
