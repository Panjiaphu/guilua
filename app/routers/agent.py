from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.services.commercial import (
    create_content_post,
    log_agent_request,
    parse_json_list,
    verify_agent_key,
)
from app.services.media import save_uploaded_image
from app.services.security_firewall import log_security_event


router = APIRouter(prefix="/api/agent", tags=["ai-agent"])


class AgentPostPayload(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    summary: str = ""
    content: str = ""
    image_url: str = ""
    target_url: str = ""
    platform: str = "other"
    locale: str = "vi"
    tags: list[str] = Field(default_factory=list)
    status: str = "draft"
    market_session: str = ""
    market_bias: str = ""
    risk_level: str = ""
    tradingview_symbol: str = ""
    tradingview_url: str = ""
    analysis_category: str = ""


def _request_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _extract_key(authorization: str | None, x_ai_agent_key: str | None) -> str | None:
    if x_ai_agent_key:
        return x_ai_agent_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_agent_key(
    request: Request,
    db: Session = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
    x_ai_agent_key: Annotated[str | None, Header()] = None,
):
    settings = get_settings()
    if not settings.ai_agent_api_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI agent API is disabled")
    agent_key = verify_agent_key(db, _extract_key(authorization, x_ai_agent_key))
    if not agent_key:
        log_agent_request(
            db,
            agent_key=None,
            endpoint=request.url.path,
            post_type="",
            request_ip=_request_ip(request),
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_message="Invalid AI agent key",
        )
        log_security_event(
            db,
            request=request,
            event_type="ai_agent_auth_failed",
            severity="medium",
            risk_score=45,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid AI agent key")
    return agent_key


@router.get("/health")
def health():
    return {"ok": True, "service": "guilua-ai-agent-api"}


@router.post("/posts/{post_type}")
def create_agent_post(
    request: Request,
    post_type: str,
    payload: AgentPostPayload,
    db: Session = Depends(get_db),
    agent_key=Depends(require_agent_key),
):
    if post_type not in {"job", "shop", "crypto_analysis"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported post type")
    allowed = set(parse_json_list(agent_key.allowed_post_types))
    if post_type not in allowed:
        log_agent_request(
            db,
            agent_key=agent_key,
            endpoint=request.url.path,
            post_type=post_type,
            request_ip=_request_ip(request),
            status_code=status.HTTP_403_FORBIDDEN,
            error_message="Post type is not allowed for this key",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Post type is not allowed")

    settings = get_settings()
    requested_status = payload.status if payload.status in {"draft", "published", "archived"} else "draft"
    final_status = requested_status
    if requested_status == "published" and not (settings.ai_agent_allow_autopublish and agent_key.can_auto_publish):
        final_status = settings.ai_agent_default_post_status
    if final_status not in {"draft", "published", "archived"}:
        final_status = "draft"

    try:
        post = create_content_post(
            db,
            post_type=post_type,
            title=payload.title,
            summary=payload.summary,
            content=payload.content,
            image_url=payload.image_url,
            target_url=payload.target_url,
            platform=payload.platform,
            locale=payload.locale,
            status=final_status,
            source="ai_agent",
            ai_agent_name=agent_key.name,
            tags=payload.tags,
            market_session=payload.market_session,
            market_bias=payload.market_bias,
            risk_level=payload.risk_level,
            tradingview_symbol=payload.tradingview_symbol,
            tradingview_url=payload.tradingview_url,
            analysis_category=payload.analysis_category,
        )
    except ValueError as exc:
        log_agent_request(
            db,
            agent_key=agent_key,
            endpoint=request.url.path,
            post_type=post_type,
            request_ip=_request_ip(request),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_message=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    log_agent_request(
        db,
        agent_key=agent_key,
        endpoint=request.url.path,
        post_type=post_type,
        request_ip=_request_ip(request),
        status_code=200,
        created_post_id=post.id,
    )
    log_security_event(
        db,
        request=request,
        event_type="ai_agent_post_created",
        severity="info",
        risk_score=10,
        status_code=200,
        details={"post_type": post_type, "post_id": post.id},
    )
    admin_section = {"job": "jobs", "shop": "shop", "crypto_analysis": "crypto-analysis"}[post_type]
    return {
        "ok": True,
        "post_id": post.id,
        "status": post.status.value,
        "admin_url": f"/admin/posts/{admin_section}/{post.id}/edit",
    }


@router.post("/media")
async def upload_agent_media(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    agent_key=Depends(require_agent_key),
):
    content = await file.read()
    try:
        saved = save_uploaded_image(
            content=content,
            original_filename=file.filename or "image",
            folder="agent",
            name_hint=agent_key.prefix,
        )
    except ValueError as exc:
        error = str(exc)
        if error == "image_too_large":
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large") from exc
        if error == "unsupported_upload_storage":
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Only local upload is implemented") from exc
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only image files are allowed") from exc
    log_agent_request(
        db,
        agent_key=agent_key,
        endpoint=request.url.path,
        post_type="media",
        request_ip=_request_ip(request),
        status_code=200,
    )
    return {
        "ok": True,
        "image_url": saved.url,
        "width": saved.width,
        "height": saved.height,
        "compressed_bytes": saved.compressed_bytes,
    }
