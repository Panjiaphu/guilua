from datetime import datetime, timezone
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EmailNotification, EmailStatus, TransactionRequest, User


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
