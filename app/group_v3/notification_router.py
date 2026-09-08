from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.group_v3.auth import require_group_actor, require_write_origin
from app.group_v3.notification_schemas import (
    GroupNotificationPreferenceUpdate,
    GroupNotificationPresenceHeartbeat,
    GroupNotificationReadUpdate,
)
from app.group_v3.service import GroupServiceError


router = APIRouter(prefix="/api/group", tags=["group-v3-notifications"])


def _json(payload: object) -> JSONResponse:
    return JSONResponse(
        payload,
        headers={
            "Cache-Control": "no-store, private, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _id(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not 1 <= len(normalized) <= 36:
        raise GroupServiceError(f"invalid_{name}", 400)
    return normalized


@router.get("/spaces/{space_id}/notifications/preferences")
async def get_group_notification_preferences(request: Request, space_id: str) -> JSONResponse:
    actor = require_group_actor(request, "group.spaces.read")
    preferences = request.app.state.group_notification_service.preferences(
        actor, _id(space_id, "space_id")
    )
    return _json({"preferences": preferences})


@router.put("/spaces/{space_id}/notifications/preferences")
async def update_group_notification_preferences(
    request: Request,
    space_id: str,
    body: GroupNotificationPreferenceUpdate,
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.spaces.read")
    preferences = request.app.state.group_notification_service.update_preferences(
        actor,
        _id(space_id, "space_id"),
        body.mode,
        body.mute_for_minutes,
    )
    return _json({"preferences": preferences})


@router.post("/spaces/{space_id}/notifications/presence")
async def group_notification_presence(
    request: Request,
    space_id: str,
    body: GroupNotificationPresenceHeartbeat,
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.spaces.read")
    normalized_space_id = _id(space_id, "space_id")
    membership_id = request.app.state.group_notification_service.membership_id(
        actor, normalized_space_id
    )
    recorded = await request.app.state.group_notification_presence.heartbeat(
        normalized_space_id,
        membership_id,
        body.tab_id,
        body.surface,
        body.visible,
    )
    return _json({"presence": {"recorded": recorded, "ttl_seconds": 75}})


@router.post("/spaces/{space_id}/notifications/read")
async def mark_group_notifications_read(
    request: Request,
    space_id: str,
    body: GroupNotificationReadUpdate,
) -> JSONResponse:
    require_write_origin(request)
    actor = require_group_actor(request, "group.messages.read")
    preferences = request.app.state.group_notification_service.mark_read(
        actor,
        _id(space_id, "space_id"),
        body.last_seen_sequence,
    )
    return _json({"preferences": preferences})
