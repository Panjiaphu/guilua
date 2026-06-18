from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.security import require_admin, verify_csrf
from app.core.templates import context, templates
from app.db.session import get_db
from app.models import EmailNotification, TransactionRequest, TransactionStatus
from app.services.email import queue_email
from app.services.rates import latest_rates, update_manual_rate


router = APIRouter(prefix="/admin")


@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    requests = db.query(TransactionRequest).order_by(TransactionRequest.created_at.desc()).limit(50).all()
    emails = db.query(EmailNotification).order_by(EmailNotification.created_at.desc()).limit(20).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context=context(
            request,
            admin=admin,
            requests=requests,
            rates=latest_rates(db),
            emails=emails,
            statuses=list(TransactionStatus),
        ),
    )


@router.post("/requests/{request_id}")
def update_request(
    request: Request,
    request_id: int,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    status: str = Form(...),
    admin_note: str = Form(""),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    item = db.get(TransactionRequest, request_id)
    if not item:
        return RedirectResponse("/admin?error=not_found", status_code=303)
    item.status = TransactionStatus(status)
    item.admin_note = admin_note.strip()
    db.commit()
    db.refresh(item)
    queue_email(
        db,
        item.user.email,
        f"Guilua request update: {item.reference_code}",
        f"Your request status is now {item.status.value}. Admin note: {item.admin_note or '-'}",
        "member_transaction_status",
        user=item.user,
        transaction=item,
    )
    return RedirectResponse("/admin?updated=1", status_code=303)


@router.post("/rates")
def update_rate(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    pair: str = Form(...),
    buy_rate: str = Form(...),
    sell_rate: str = Form(...),
    note: str = Form(""),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    try:
        parsed_buy = Decimal(buy_rate)
        parsed_sell = Decimal(sell_rate)
    except InvalidOperation:
        return RedirectResponse("/admin?error=invalid_rate", status_code=303)
    if parsed_buy <= 0 or parsed_sell <= 0:
        return RedirectResponse("/admin?error=invalid_rate", status_code=303)
    update_manual_rate(db, pair=pair, buy_rate=parsed_buy, sell_rate=parsed_sell, note=note.strip())
    return RedirectResponse("/admin?rate_updated=1", status_code=303)
