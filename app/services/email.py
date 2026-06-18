from datetime import datetime, timezone
import json
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EmailNotification, EmailReply, EmailStatus, TransactionRequest, User


def queue_email(
    db: Session,
    recipient: str,
    subject: str,
    body: str,
    event_type: str,
    user: User | None = None,
    transaction: TransactionRequest | None = None,
) -> EmailNotification:
    item = EmailNotification(
        recipient=recipient,
        subject=subject,
        body=body,
        event_type=event_type,
        user_id=user.id if user else None,
        transaction_id=transaction.id if transaction else None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def send_queued_email(item: EmailNotification) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST is not configured")
    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = item.recipient
    message["Subject"] = item.subject
    message.set_content(item.body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
        if settings.smtp_use_tls:
            client.starttls()
        if settings.smtp_username and settings.smtp_password:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)


def flush_email_queue(db: Session, limit: int = 20) -> list[EmailNotification]:
    pending = (
        db.query(EmailNotification)
        .filter(EmailNotification.status == EmailStatus.QUEUED)
        .order_by(EmailNotification.created_at.asc())
        .limit(limit)
        .all()
    )
    for item in pending:
        try:
            send_queued_email(item)
        except Exception as exc:  # noqa: BLE001 - store provider failure for admin review
            item.status = EmailStatus.FAILED
            item.error = str(exc)
        else:
            item.status = EmailStatus.SENT
            item.sent_at = datetime.now(timezone.utc)
    db.commit()
    return pending


def record_email_reply(
    db: Session,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    provider_message_id: str = "",
    raw_payload: dict | None = None,
) -> EmailReply:
    normalized_sender = sender.strip().lower()
    user = db.query(User).filter(User.email == normalized_sender).first()
    transaction = _match_transaction(db, subject=subject, body=body)
    reply = EmailReply(
        sender=normalized_sender,
        recipient=recipient.strip().lower(),
        subject=subject.strip(),
        body=body.strip(),
        provider_message_id=provider_message_id.strip(),
        raw_payload=json.dumps(raw_payload or {}, ensure_ascii=False),
        user_id=user.id if user else None,
        transaction_id=transaction.id if transaction else None,
        is_processed=False,
    )
    db.add(reply)
    settings = get_settings()
    if settings.admin_notification_email:
        reference = f"\nMã yêu cầu: {transaction.reference_code}" if transaction else ""
        db.add(
            EmailNotification(
                recipient=settings.admin_notification_email,
                subject=f"Guilua - email phản hồi từ {normalized_sender}",
                body=f"Member vừa phản hồi email.{reference}\n\nTiêu đề: {subject.strip() or '-'}\n\n{body.strip()}",
                event_type="inbound_email_reply",
                user_id=user.id if user else None,
                transaction_id=transaction.id if transaction else None,
            )
        )
    db.commit()
    db.refresh(reply)
    return reply


def mark_reply_processed(db: Session, reply_id: int) -> EmailReply | None:
    reply = db.get(EmailReply, reply_id)
    if not reply:
        return None
    reply.is_processed = True
    db.commit()
    db.refresh(reply)
    return reply


def _match_transaction(db: Session, subject: str, body: str) -> TransactionRequest | None:
    haystack = f"{subject}\n{body}".upper()
    for token in haystack.replace("#", " ").replace(":", " ").replace("-", " ").split():
        if token.startswith("GL") and len(token) >= 6:
            found = db.query(TransactionRequest).filter(TransactionRequest.reference_code == token).first()
            if found:
                return found
    return None
