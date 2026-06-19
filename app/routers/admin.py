from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.security import require_admin, verify_csrf
from app.core.templates import context, templates
from app.db.session import get_db
from app.models import EmailNotification, EmailReply, ServiceRequest, TransactionRequest, TransactionStatus
from app.services.email import flush_email_queue, mark_reply_processed, queue_email
from app.services.rates import latest_rates, update_manual_rate


router = APIRouter(prefix="/admin")


@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    requests = db.query(TransactionRequest).order_by(TransactionRequest.created_at.desc()).limit(50).all()
    service_requests = db.query(ServiceRequest).order_by(ServiceRequest.created_at.desc()).limit(50).all()
    emails = db.query(EmailNotification).order_by(EmailNotification.created_at.desc()).limit(20).all()
    replies = db.query(EmailReply).order_by(EmailReply.created_at.desc()).limit(20).all()
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context=context(
            request,
            admin=admin,
            requests=requests,
            service_requests=service_requests,
            rates=latest_rates(db),
            emails=emails,
            replies=replies,
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
        f"Guilua - cập nhật yêu cầu {item.reference_code}",
        f"Trạng thái yêu cầu hiện tại: {item.status.value}. Ghi chú quản trị: {item.admin_note or '-'}",
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


@router.post("/services/{service_id}")
def update_service_request(
    request: Request,
    service_id: int,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    status: str = Form(...),
    assigned_endpoint: str = Form(""),
    admin_note: str = Form(""),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    item = db.get(ServiceRequest, service_id)
    if not item:
        return RedirectResponse("/admin?error=service_not_found", status_code=303)
    if status not in {state.value for state in TransactionStatus}:
        return RedirectResponse("/admin?error=invalid_service_status", status_code=303)
    item.status = status
    item.assigned_endpoint = assigned_endpoint.strip()
    item.admin_note = admin_note.strip()
    db.commit()
    db.refresh(item)
    queue_email(
        db,
        item.user.email,
        f"Guilua - cập nhật dịch vụ {item.reference_code}",
        (
            f"Trạng thái dịch vụ chuyển IP hiện tại: {item.status}. "
            f"Endpoint: {item.assigned_endpoint or '-'}. "
            f"Ghi chú quản trị: {item.admin_note or '-'}"
        ),
        "member_service_status",
        user=item.user,
    )
    return RedirectResponse("/admin?service_updated=1", status_code=303)


@router.post("/email/flush")
def flush_emails(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    sent = flush_email_queue(db)
    return RedirectResponse(f"/admin?email_flush={len(sent)}", status_code=303)


@router.post("/email-replies/{reply_id}/processed")
def process_email_reply(
    request: Request,
    reply_id: int,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
):
    verify_csrf(request, csrf_token)
    require_admin(request, db)
    mark_reply_processed(db, reply_id)
    return RedirectResponse("/admin?reply_processed=1", status_code=303)
