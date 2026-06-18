from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.security import require_user, verify_csrf
from app.core.templates import context, templates
from app.db.session import get_db
from app.models import TransactionRequest, TransactionType
from app.services.rates import latest_rates
from app.services.transactions import create_transaction


router = APIRouter(prefix="/member")


@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    requests = (
        db.query(TransactionRequest)
        .filter(TransactionRequest.user_id == user.id)
        .order_by(TransactionRequest.created_at.desc())
        .limit(20)
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="member/dashboard.html",
        context=context(request, user=user, requests=requests, rates=latest_rates(db), error=""),
    )


@router.post("/requests")
def create_request(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    request_type: str = Form(...),
    amount_twd: str = Form(""),
    amount_usdt: str = Form(""),
    recipient_name: str = Form(""),
    recipient_bank: str = Form(""),
    recipient_account: str = Form(""),
    member_note: str = Form(""),
):
    verify_csrf(request, csrf_token)
    user = require_user(request, db)
    try:
        parsed_type = TransactionType(request_type)
        parsed_twd = Decimal(amount_twd) if amount_twd.strip() else None
        parsed_usdt = Decimal(amount_usdt) if amount_usdt.strip() else None
    except (ValueError, InvalidOperation):
        return RedirectResponse("/member?error=invalid_amount", status_code=303)
    if parsed_twd is not None and parsed_twd <= 0:
        return RedirectResponse("/member?error=invalid_amount", status_code=303)
    if parsed_usdt is not None and parsed_usdt <= 0:
        return RedirectResponse("/member?error=invalid_amount", status_code=303)
    create_transaction(
        db,
        user=user,
        request_type=parsed_type,
        amount_twd=parsed_twd,
        amount_usdt=parsed_usdt,
        recipient_name=recipient_name.strip(),
        recipient_bank=recipient_bank.strip(),
        recipient_account=recipient_account.strip(),
        member_note=member_note.strip(),
    )
    return RedirectResponse("/member?created=1", status_code=303)
