from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.group_v3.auth import require_group_actor, require_write_origin
from app.group_v3.radio_schemas import RadioFloorAcquire, RadioFloorToken, RadioMediaGrant, RadioSessionCreate
from app.group_v3.service import GroupServiceError
from app.group_v3.voice_input import read_voice_form


router = APIRouter(prefix="/api/group", tags=["group-v3-radio"])


def _json(payload: object, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code, headers={"Cache-Control": "no-store, private, max-age=0", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"})


def _id(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not 1 <= len(normalized) <= 36:
        raise HTTPException(status_code=400, detail=f"invalid_{name}")
    return normalized


@router.get("/spaces/{space_id}/radio/sessions")
async def list_radio_sessions(request: Request, space_id: str, status: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=100)) -> JSONResponse:
    actor = require_group_actor(request, "group.radio.use")
    if status not in {None, "ready", "ended"}:
        raise HTTPException(status_code=400, detail="invalid_radio_status")
    sessions = request.app.state.group_radio_service.list_sessions(actor, _id(space_id, "space_id"), status, limit)
    return _json({"sessions": sessions})


@router.post("/spaces/{space_id}/radio/room/join")
async def open_radio_room(request: Request, space_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    normalized = _id(space_id, "space_id")
    session = request.app.state.group_radio_service.open_room(actor, normalized)
    await request.app.state.group_event_broker.publish(normalized, "radio.participant_joined", resource_id=session["id"])
    return _json({"session": session})


@router.post("/spaces/{space_id}/radio/sessions")
async def create_radio_session(request: Request, space_id: str, body: RadioSessionCreate) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    normalized_space = _id(space_id, "space_id")
    session = request.app.state.group_radio_service.create_session(actor, normalized_space, body.model_dump())
    await request.app.state.group_event_broker.publish(normalized_space, "radio.session_created", resource_id=session["id"])
    return _json({"session": session}, status_code=201)


@router.get("/spaces/{space_id}/radio/sessions/{session_id}")
async def get_radio_session(request: Request, space_id: str, session_id: str) -> JSONResponse:
    actor = require_group_actor(request, "group.radio.use")
    session = request.app.state.group_radio_service.get_session(actor, _id(space_id, "space_id"), _id(session_id, "session_id"))
    floor = await request.app.state.group_radio_floor.snapshot(session["id"])
    return _json({"session": session, "floor": floor})


@router.post("/spaces/{space_id}/radio/sessions/{session_id}/join")
async def join_radio_session(request: Request, space_id: str, session_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    normalized_space = _id(space_id, "space_id")
    session = request.app.state.group_radio_service.join(actor, normalized_space, _id(session_id, "session_id"))
    await request.app.state.group_event_broker.publish(normalized_space, "radio.participant_joined", resource_id=session["id"])
    return _json({"session": session})


@router.post("/spaces/{space_id}/radio/sessions/{session_id}/reject")
async def reject_radio_session(request: Request, space_id: str, session_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    normalized_space = _id(space_id, "space_id")
    session = request.app.state.group_radio_service.reject(
        actor,
        normalized_space,
        _id(session_id, "session_id"),
    )
    await request.app.state.group_event_broker.publish(normalized_space, "radio.participant_rejected", resource_id=session["id"])
    return _json({"session": session, "rejected": True})


@router.post("/spaces/{space_id}/radio/sessions/{session_id}/leave")
async def leave_radio_session(request: Request, space_id: str, session_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    normalized_space = _id(space_id, "space_id")
    normalized_session = _id(session_id, "session_id")
    member_id = request.app.state.group_radio_service.leave_context(actor, normalized_space, normalized_session)
    await request.app.state.group_radio_floor.release_membership(normalized_session, member_id)
    session = request.app.state.group_radio_service.leave(actor, normalized_space, normalized_session)
    await request.app.state.group_event_broker.publish(normalized_space, "radio.participant_left", resource_id=normalized_session)
    return _json({"session": session, "ended_for_all": False})


@router.post("/spaces/{space_id}/radio/sessions/{session_id}/end-for-all")
async def end_radio_session_for_all(request: Request, space_id: str, session_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    normalized_session = _id(session_id, "session_id")
    if await request.app.state.group_radio_floor.snapshot(normalized_session):
        raise HTTPException(status_code=409, detail="group_radio_stop_burst_before_end")
    normalized_space = _id(space_id, "space_id")
    session = request.app.state.group_radio_service.end_for_all(actor, normalized_space, normalized_session)
    await request.app.state.group_event_broker.publish(normalized_space, "radio.session_ended", resource_id=normalized_session)
    return _json({"session": session, "ended_for_all": True})


@router.post("/spaces/{space_id}/radio/sessions/{session_id}/floor/acquire")
async def acquire_radio_floor(request: Request, space_id: str, session_id: str, body: RadioFloorAcquire) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    normalized_space = _id(space_id, "space_id")
    normalized_session = _id(session_id, "session_id")
    _session, participant = request.app.state.group_radio_service.floor_context(actor, normalized_space, normalized_session)
    floor = await request.app.state.group_radio_floor.acquire(normalized_session, participant_id=participant["id"], membership_id=participant["membership_id"], display_name=participant["display_name"])
    try:
        burst = request.app.state.group_radio_service.record_burst(actor, normalized_space, normalized_session, floor["token"], body.source_language, body.target_languages)
    except Exception:
        try:
            await request.app.state.group_radio_floor.release(normalized_session, floor["token"])
        except GroupServiceError:
            pass
        raise
    await request.app.state.group_event_broker.publish(normalized_space, "radio.floor_acquired", resource_id=burst["id"])
    return _json({"floor_token": floor["token"], "lease_expires_at_ms": floor["lease_expires_at_ms"], "deadline_ms": floor["deadline_ms"], "burst": burst}, status_code=201)


@router.post("/spaces/{space_id}/radio/sessions/{session_id}/floor/heartbeat")
async def heartbeat_radio_floor(request: Request, space_id: str, session_id: str, body: RadioFloorToken) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    normalized_space = _id(space_id, "space_id")
    normalized_session = _id(session_id, "session_id")
    burst = request.app.state.group_radio_service.burst_for_token(actor, normalized_space, normalized_session, body.floor_token)
    if burst["state"] != "talking":
        return _json({"burst": burst, "floor_released": True})
    try:
        lease = await request.app.state.group_radio_floor.heartbeat(normalized_session, body.floor_token)
    except GroupServiceError as exc:
        if exc.code != "group_radio_max_burst_reached":
            raise
        burst = request.app.state.group_radio_service.stop_burst_after_floor_release(actor, normalized_space, normalized_session, body.floor_token, reason="max_burst")
        await request.app.state.group_event_broker.publish(normalized_space, "radio.floor_released", resource_id=burst["id"])
        return _json({"burst": burst, "floor_released": True, "max_burst_reached": True})
    return _json({"burst": burst, **lease})


@router.post("/spaces/{space_id}/radio/sessions/{session_id}/floor/stop")
async def stop_radio_burst(request: Request, space_id: str, session_id: str, body: RadioFloorToken) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    normalized_space = _id(space_id, "space_id")
    normalized_session = _id(session_id, "session_id")
    existing = request.app.state.group_radio_service.burst_for_token(actor, normalized_space, normalized_session, body.floor_token)
    if existing["state"] == "talking":
        try:
            await request.app.state.group_radio_floor.release(normalized_session, body.floor_token)
        except GroupServiceError as exc:
            if exc.code != "group_radio_floor_not_owned":
                raise
    burst = request.app.state.group_radio_service.stop_burst_after_floor_release(actor, normalized_space, normalized_session, body.floor_token)
    await request.app.state.group_event_broker.publish(normalized_space, "radio.floor_released", resource_id=burst["id"])
    return _json({"burst": burst, "floor_released_before_downstream": True, "downstream_state": "FINALIZING_BURST" if burst["state"] == "finalizing" else "FINAL"})


@router.post("/spaces/{space_id}/radio/sessions/{session_id}/floor/device-lost")
async def radio_device_lost(request: Request, space_id: str, session_id: str, body: RadioFloorToken) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    normalized_space = _id(space_id, "space_id")
    normalized_session = _id(session_id, "session_id")
    existing = request.app.state.group_radio_service.burst_for_token(actor, normalized_space, normalized_session, body.floor_token)
    if existing["state"] == "talking":
        try:
            await request.app.state.group_radio_floor.release(normalized_session, body.floor_token)
        except GroupServiceError as exc:
            if exc.code != "group_radio_floor_not_owned":
                raise
    burst = request.app.state.group_radio_service.device_lost_after_floor_release(actor, normalized_space, normalized_session, body.floor_token)
    await request.app.state.group_event_broker.publish(normalized_space, "radio.device_lost", resource_id=burst["id"])
    return _json({"burst": burst, "floor_released_before_downstream": True, "private_audio_playback": "suppressed", "auto_read": "suppressed"})


@router.post("/spaces/{space_id}/radio/sessions/{session_id}/media-grant")
async def radio_media_grant(request: Request, space_id: str, session_id: str, body: RadioMediaGrant) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    normalized_space = _id(space_id, "space_id")
    normalized_session = _id(session_id, "session_id")
    _session, participant = request.app.state.group_radio_service.floor_context(actor, normalized_space, normalized_session)
    can_publish = body.mode == "talk"
    if can_publish:
        if not body.floor_token:
            raise HTTPException(status_code=400, detail="floor_token_required")
        await request.app.state.group_radio_floor.assert_owner(normalized_session, body.floor_token, participant["id"])
    grant = request.app.state.group_radio_service.issue_media_grant(actor, normalized_space, normalized_session, can_publish=can_publish)
    return _json({"grant": grant})


@router.get("/spaces/{space_id}/radio/sessions/{session_id}/history")
async def radio_history(request: Request, space_id: str, session_id: str, limit: int = Query(default=50, ge=1, le=100)) -> JSONResponse:
    actor = require_group_actor(request, "group.radio.use")
    bursts = request.app.state.group_radio_service.history(actor, _id(space_id, "space_id"), _id(session_id, "session_id"), limit)
    return _json({"bursts": bursts})


@router.get("/spaces/{space_id}/radio/history")
async def radio_room_history(request: Request, space_id: str,
                             limit: int = Query(default=50, ge=1, le=100),
                             before_id: str | None = Query(default=None, max_length=36)) -> JSONResponse:
    actor = require_group_actor(request, "group.radio.use")
    result = request.app.state.group_radio_service.room_history(
        actor, _id(space_id, "space_id"), request.app.state.group_translation_service, limit, before_id
    )
    return _json({"bursts": result})


@router.post("/spaces/{space_id}/radio/sessions/{session_id}/bursts/{burst_id}/transcribe")
async def transcribe_radio_burst(request: Request, space_id: str, session_id: str, burst_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    fields, audio, filename, content_type = await read_voice_form(request)
    normalized_burst = _id(burst_id, "burst_id")
    if request.headers.get("Idempotency-Key", normalized_burst) != normalized_burst:
        raise HTTPException(400, "group_translation_idempotency_mismatch")
    result = await request.app.state.group_translation_service.submit_radio_voice(
        actor, _id(space_id, "space_id"), _id(session_id, "session_id"), normalized_burst,
        fields, audio, filename, content_type,
    )
    return _json({"segment": result})


@router.post("/spaces/{space_id}/radio/sessions/{session_id}/bursts/{burst_id}/discard")
async def discard_radio_clip(request: Request, space_id: str, session_id: str, burst_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.radio.use")
    request.app.state.group_translation_service.discard_radio_clip(
        actor, _id(space_id, "space_id"), _id(session_id, "session_id"), _id(burst_id, "burst_id")
    )
    await request.app.state.group_event_broker.publish(space_id, "radio.message_changed", resource_id=burst_id)
    return _json({"discarded": True})
