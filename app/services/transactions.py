from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import TransactionRequest, TransactionStatus, TransactionType, User
from app.services.email import queue_email
from app.services.rates import latest_rates


def make_reference() -> str:
    return f"GL{uuid4().hex[:12].upper()}"


def create_transaction(
    db: Session,
    user: User,
    request_type: TransactionType,
    amount_twd: Decimal | None,
    amount_usdt: Decimal | None,
    recipient_name: str = "",
    recipient_bank: str = "",
    recipient_account: str = "",
    member_note: str = "",
) -> TransactionRequest:
    rates = latest_rates(db)
    rate_pair = "TWD_VND" if request_type == TransactionType.SEND_HOME else "USDT_TWD"
    rate = rates[rate_pair]
    rate_value = Decimal(str(rate.buy_rate if request_type != TransactionType.SELL_USDT else rate.sell_rate))
    amount_vnd = amount_twd * rate_value if request_type == TransactionType.SEND_HOME and amount_twd else None
    if request_type == TransactionType.BUY_USDT and amount_twd:
        amount_usdt = amount_twd / rate_value
    if request_type == TransactionType.SELL_USDT and amount_usdt:
        amount_twd = amount_usdt * rate_value

    item = TransactionRequest(
        reference_code=make_reference(),
        user_id=user.id,
        request_type=request_type,
        status=TransactionStatus.PENDING,
        amount_twd=amount_twd,
        amount_vnd=amount_vnd,
        amount_usdt=amount_usdt,
        rate_pair=rate_pair,
        rate_value=rate_value,
        recipient_name=recipient_name,
        recipient_bank=recipient_bank,
        recipient_account=recipient_account,
        member_note=member_note,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    queue_email(
        db,
        user.email,
        f"Guilua request received: {item.reference_code}",
        f"Your request {item.reference_code} is pending admin review.",
        "member_transaction_created",
        user=user,
        transaction=item,
    )
    admin_email = get_settings().admin_notification_email
    if admin_email:
        queue_email(
            db,
            admin_email,
            f"New Guilua request: {item.reference_code}",
            f"New {item.request_type.value} request from {user.email}.",
            "admin_transaction_created",
            user=user,
            transaction=item,
        )
    return item
