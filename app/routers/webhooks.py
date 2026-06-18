from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.services.email import record_email_reply


router = APIRouter(prefix="/webhooks")


@router.post("/email-reply")
async def email_reply_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_guilua_webhook_key: str | None = Header(default=None),
):
    settings = get_settings()
    if not settings.email_webhook_api_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email webhook is not configured")
    if x_guilua_webhook_key != settings.email_webhook_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook key")

    payload = await request.json()
    sender = payload.get("from") or payload.get("sender") or payload.get("email")
    subject = payload.get("subject") or ""
    body = payload.get("text") or payload.get("body") or payload.get("html") or ""
    if not sender or not body:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing sender or body")

    reply = record_email_reply(
        db,
        sender=str(sender),
        recipient=str(payload.get("to") or payload.get("recipient") or ""),
        subject=str(subject),
        body=str(body),
        provider_message_id=str(payload.get("message_id") or payload.get("messageId") or ""),
        raw_payload=payload,
    )
    return {"status": "ok", "reply_id": reply.id, "matched_transaction_id": reply.transaction_id}
