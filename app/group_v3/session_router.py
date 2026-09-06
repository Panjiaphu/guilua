from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.group_v3.auth import require_group_actor, require_write_origin
from app.group_v3.session_schemas import (
    MediaConnectionStateUpdate,
    MediaSessionCreate,
    VideoSubscriptionsUpdate,
)


router = APIRouter(prefix="/api/group", tags=["group-v3-media"])


def _event_broker(request: Request):
    return request.app.state.group_event_broker


async def _publish(request: Request, space_id: str, event_type: str, resource_id: object = "") -> None:
    await _event_broker(request).publish(space_id, event_type, resource_id=resource_id)


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


def _id(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not 1 <= len(normalized) <= 36:
        raise HTTPException(status_code=400, detail=f"invalid_{name}")
    return normalized


@router.get("/spaces/{space_id}/sessions")
async def list_sessions(
    request: Request,
    space_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> JSONResponse:
    actor = require_group_actor(request, "group.media.use")
    if status not in {None, "ringing", "active", "ended"}:
        raise HTTPException(status_code=400, detail="invalid_group_media_status")
    sessions = request.app.state.group_media_session_service.list_sessions(
        actor,
        _id(space_id, "space_id"),
        status,
        limit,
    )
    return _json({"sessions": sessions})


@router.post("/spaces/{space_id}/sessions")
async def create_session(
    request: Request,
    space_id: str,
    body: MediaSessionCreate,
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.media.use")
    session = request.app.state.group_media_session_service.create_session(
        actor,
        _id(space_id, "space_id"),
        body.model_dump(),
    )
    await _publish(request, session["space_id"], "media_session.created", session["id"])
    return _json({"session": session}, status_code=201)


@router.get("/spaces/{space_id}/sessions/{session_id}")
async def get_session(request: Request, space_id: str, session_id: str) -> JSONResponse:
    actor = require_group_actor(request, "group.media.use")
    session = request.app.state.group_media_session_service.get_session(
        actor,
        _id(space_id, "space_id"),
        _id(session_id, "session_id"),
    )
    return _json({"session": session})


@router.post("/spaces/{space_id}/sessions/{session_id}/join")
async def join_session(request: Request, space_id: str, session_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.media.use")
    session = request.app.state.group_media_session_service.join(
        actor,
        _id(space_id, "space_id"),
        _id(session_id, "session_id"),
    )
    await _publish(request, session["space_id"], "media_session.joined", session["id"])
    return _json({"session": session})


@router.post("/spaces/{space_id}/sessions/{session_id}/reject")
async def reject_session(request: Request, space_id: str, session_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.media.use")
    session = request.app.state.group_media_session_service.reject(
        actor,
        _id(space_id, "space_id"),
        _id(session_id, "session_id"),
    )
    await _publish(request, session["space_id"], "media_session.rejected", session["id"])
    return _json({"session": session})


@router.post("/spaces/{space_id}/sessions/{session_id}/leave")
async def leave_session(request: Request, space_id: str, session_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.media.use")
    session = request.app.state.group_media_session_service.leave(
        actor,
        _id(space_id, "space_id"),
        _id(session_id, "session_id"),
    )
    await _publish(request, session["space_id"], "media_session.left", session["id"])
    return _json({"session": session, "ended_for_all": False})


@router.post("/spaces/{space_id}/sessions/{session_id}/end-for-all")
async def end_session_for_all(request: Request, space_id: str, session_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.media.use")
    session = request.app.state.group_media_session_service.end_for_all(
        actor,
        _id(space_id, "space_id"),
        _id(session_id, "session_id"),
    )
    await _publish(request, session["space_id"], "media_session.ended_for_all", session["id"])
    return _json({"session": session, "ended_for_all": True})


@router.post("/spaces/{space_id}/sessions/{session_id}/connection-state")
async def update_connection_state(
    request: Request,
    space_id: str,
    session_id: str,
    body: MediaConnectionStateUpdate,
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.media.use")
    normalized_space_id = _id(space_id, "space_id")
    session = request.app.state.group_media_session_service.update_connection_state(
        actor,
        normalized_space_id,
        _id(session_id, "session_id"),
        body.status,
        body.failure_code,
    )
    await _publish(request, normalized_space_id, "media_session.connection_state", session["id"])
    return _json({"session": session})


@router.put("/spaces/{space_id}/sessions/{session_id}/video-subscriptions")
async def update_video_subscriptions(
    request: Request,
    space_id: str,
    session_id: str,
    body: VideoSubscriptionsUpdate,
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.media.use")
    result = request.app.state.group_media_session_service.update_video_subscriptions(
        actor,
        _id(space_id, "space_id"),
        _id(session_id, "session_id"),
        body.participant_membership_ids,
    )
    await _publish(request, _id(space_id, "space_id"), "media_session.video_subscriptions_updated", _id(session_id, "session_id"))
    return _json(result)


@router.post("/spaces/{space_id}/sessions/{session_id}/media-grant")
async def create_media_grant(request: Request, space_id: str, session_id: str) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.media.use")
    grant = request.app.state.group_media_session_service.media_grant(
        actor,
        _id(space_id, "space_id"),
        _id(session_id, "session_id"),
    )
    return _json({"grant": grant})
