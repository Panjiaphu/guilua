from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.group_translation.provider import GroupTranslationProviderError
from app.group_v3.auth import require_group_actor, require_write_origin
from app.group_v3.voice_input import read_voice_form
from app.group_v3.translation_schemas import (
    LanguageProfileUpdate,
    TranslationConsentUpdate,
    TranslationFinalCreate,
    TranslationReservationRelease,
    TranslationSecretCreate,
    TranslationSegmentTextCreate,
    TranslationVariantRetry,
    TtsJobAck,
)


router = APIRouter(prefix="/api/group", tags=["group-v3-translation"])


def _json(payload: object, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        payload,
        status_code=status_code,
        headers={
            "Cache-Control": "no-store, private, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _id(value: str, name: str, maximum: int = 36) -> str:
    normalized = str(value or "").strip()
    if not 1 <= len(normalized) <= maximum:
        raise HTTPException(status_code=400, detail=f"invalid_{name}")
    return normalized


@router.get("/spaces/{space_id}/translation/profile")
async def get_language_profile(request: Request, space_id: str) -> JSONResponse:
    actor = require_group_actor(request, "group.translation.use")
    profile = request.app.state.group_translation_service.get_profile(actor, _id(space_id, "space_id"))
    return _json({"profile": profile})


@router.put("/spaces/{space_id}/translation/profile")
async def update_language_profile(request: Request, space_id: str, body: LanguageProfileUpdate) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.translation.use")
    profile = request.app.state.group_translation_service.update_profile(actor, _id(space_id, "space_id"), body.model_dump())
    return _json({"profile": profile})


@router.get("/spaces/{space_id}/translation/consent")
async def get_translation_consent(request: Request, space_id: str) -> JSONResponse:
    actor = require_group_actor(request, "group.translation.use")
    consent = request.app.state.group_translation_service.get_consent(actor, _id(space_id, "space_id"))
    return _json({"consent": consent})


@router.put("/spaces/{space_id}/translation/consent")
async def update_translation_consent(request: Request, space_id: str, body: TranslationConsentUpdate) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.translation.use")
    consent = request.app.state.group_translation_service.update_consent(actor, _id(space_id, "space_id"), body.status, body.policy_version)
    return _json({"consent": consent})


@router.post("/spaces/{space_id}/messages/{message_id}/translation")
async def translate_chat_message(
    request: Request,
    space_id: str,
    message_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.translation.use")
    normalized_space_id = _id(space_id, "space_id")
    result = await request.app.state.group_chat_translation_service.translate(
        actor,
        normalized_space_id,
        _id(message_id, "message_id"),
        str(idempotency_key or ""),
    )
    translation = result.get("translation")
    if (
        translation
        and translation.get("state") == "FINAL"
        and not result.get("idempotent")
    ):
        await request.app.state.group_event_broker.publish(
            normalized_space_id,
            "chat_translation.final",
            resource_id=translation["id"],
        )
    return _json(result, status_code=202 if result.get("pending") else 200)


@router.get("/spaces/{space_id}/translation/chat-history")
async def chat_translation_history(
    request: Request,
    space_id: str,
    limit: int = Query(default=100, ge=1, le=100),
) -> JSONResponse:
    actor = require_group_actor(request, "group.translation.use")
    translations = request.app.state.group_chat_translation_service.history(
        actor,
        _id(space_id, "space_id"),
        limit,
    )
    return _json({"translations": translations})


@router.get("/spaces/{space_id}/translation/quota")
async def get_translation_quota(
    request: Request,
    space_id: str,
    media_kind: str = Query(default="audio"),
) -> JSONResponse:
    actor = require_group_actor(request, "group.translation.use")
    if media_kind not in {"audio", "video", "radio"}:
        raise HTTPException(status_code=400, detail="invalid_media_kind")
    quota = request.app.state.group_translation_service.quota(actor, _id(space_id, "space_id"), media_kind)
    return _json({"quota": quota})


@router.post("/spaces/{space_id}/translation/segments/text")
async def submit_translation_text(
    request: Request,
    space_id: str,
    body: TranslationSegmentTextCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.translation.use")
    result = await request.app.state.group_translation_service.submit_text(
        actor, _id(space_id, "space_id"), body.model_dump(), idempotency_key
    )
    return _json({"segment": result}, status_code=201)


@router.post("/spaces/{space_id}/translation/segments/voice")
async def submit_translation_voice(
    request: Request,
    space_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.translation.use")
    fields, data, filename, content_type = await read_voice_form(request)
    runtime_kind = fields.get("runtime_kind")
    runtime_id = fields.get("runtime_id")
    client_segment_id = fields.get("client_segment_id")
    source_language = fields.get("source_language")
    if runtime_kind not in {"call", "video", "radio"} or source_language not in {"vi", "en", "zh-TW", "auto"}:
        raise HTTPException(status_code=400, detail="invalid_translation_segment")
    if idempotency_key and str(idempotency_key).strip() != str(client_segment_id).strip():
        raise HTTPException(status_code=400, detail="group_translation_idempotency_mismatch")
    result = await request.app.state.group_translation_service.submit_voice(
        actor,
        _id(space_id, "space_id"),
        {
            "runtime_kind": runtime_kind,
            "runtime_id": _id(runtime_id, "runtime_id"),
            "client_segment_id": _id(client_segment_id, "client_segment_id", 128),
            "source_language": source_language,
            "duration_seconds": fields.get("duration_seconds"),
        },
        data,
        filename,
        content_type,
    )
    return _json({"segment": result}, status_code=201)


@router.post("/spaces/{space_id}/translation/segments/{segment_id}/variants/{target_language}/retry")
async def retry_translation_variant(
    request: Request,
    space_id: str,
    segment_id: str,
    target_language: str,
    body: TranslationVariantRetry | None = None,
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.translation.use")
    target = body.target_language if body else target_language
    result = await request.app.state.group_translation_service.retry_variant(
        actor, _id(space_id, "space_id"), _id(segment_id, "segment_id"), target
    )
    return _json({"segment": result})


@router.get("/spaces/{space_id}/translation/v2-history")
async def translation_v2_history(
    request: Request,
    space_id: str,
    runtime_kind: str | None = Query(default=None),
    runtime_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    before_id: str | None = Query(default=None, max_length=36),
) -> JSONResponse:
    actor = require_group_actor(request, "group.translation.use")
    if runtime_kind not in {None, "call", "video", "radio"}:
        raise HTTPException(status_code=400, detail="invalid_runtime_kind")
    result = request.app.state.group_translation_service.v2_history(
        actor, _id(space_id, "space_id"), runtime_kind, _id(runtime_id, "runtime_id") if runtime_id else None, limit, before_id
    )
    return _json({"segments": result})


@router.post("/spaces/{space_id}/translation/client-secret")
async def create_translation_client_secret(
    request: Request,
    space_id: str,
    body: TranslationSecretCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.translation.use")
    normalized_space_id = _id(space_id, "space_id")
    values = body.model_dump()
    reservation = request.app.state.group_translation_service.reserve(actor, normalized_space_id, values, idempotency_key)
    try:
        secret = await request.app.state.openai_group_translation_provider.create_client_secret(
            source_language=values["source_language"],
            target_language=values["target_language"],
            principal_id=actor.key,
        )
        request.app.state.group_translation_service.mark_provider_secret(
            actor,
            reservation["reservation_id"],
            secret.session_id,
            secret.expires_at,
        )
    except GroupTranslationProviderError as exc:
        request.app.state.group_translation_service.release(actor, normalized_space_id, reservation["reservation_id"], reason=str(exc))
        status_code = 503 if str(exc) in {
            "group_translation_disabled",
            "group_translation_provider_not_configured",
            "group_translation_provider_unavailable",
        } else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception:
        request.app.state.group_translation_service.release(actor, normalized_space_id, reservation["reservation_id"], reason="provider_secret_binding_failed")
        raise
    return _json(
        {
            "provider": "openai-realtime-translate",
            "client_secret": secret.value,
            "expires_at": secret.expires_at,
            "provider_session_id": secret.session_id,
            "provider_request_id": secret.request_id,
            "translation": reservation,
        },
        status_code=201,
    )


@router.post("/spaces/{space_id}/translation/reservations/release")
async def release_translation_reservation(
    request: Request,
    space_id: str,
    body: TranslationReservationRelease,
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.translation.use")
    result = request.app.state.group_translation_service.release(actor, _id(space_id, "space_id"), body.reservation_id)
    return _json(result)


@router.post("/spaces/{space_id}/translation/final")
async def persist_final_translation(
    request: Request,
    space_id: str,
    body: TranslationFinalCreate,
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.translation.use")
    result = request.app.state.group_translation_service.finalize(actor, _id(space_id, "space_id"), body.model_dump())
    return _json(result, status_code=200 if result.get("idempotent") else 201)


@router.get("/spaces/{space_id}/translation/history")
async def translation_history(
    request: Request,
    space_id: str,
    runtime_kind: str | None = Query(default=None),
    runtime_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> JSONResponse:
    actor = require_group_actor(request, "group.translation.use")
    if runtime_kind not in {None, "call", "video", "radio"}:
        raise HTTPException(status_code=400, detail="invalid_runtime_kind")
    if runtime_id is not None:
        runtime_id = _id(runtime_id, "runtime_id")
    events = request.app.state.group_translation_service.history(actor, _id(space_id, "space_id"), runtime_kind, runtime_id, limit)
    return _json({"events": events})


@router.post("/spaces/{space_id}/translation/tts-jobs/claim")
async def claim_tts_job(request: Request, space_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.translation.use")
    job = request.app.state.group_translation_service.claim_tts_job(actor, _id(space_id, "space_id"))
    return _json({"job": job})


@router.post("/spaces/{space_id}/translation/tts-jobs/{job_id}/ack")
async def ack_tts_job(request: Request, space_id: str, job_id: str, body: TtsJobAck) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.translation.use")
    job = request.app.state.group_translation_service.ack_tts_job(actor, _id(space_id, "space_id"), _id(job_id, "job_id"), body.status, body.failure_code)
    return _json({"job": job})
