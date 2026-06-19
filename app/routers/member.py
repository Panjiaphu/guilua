from decimal import Decimal, InvalidOperation
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import require_user, verify_csrf
from app.core.templates import context, templates
from app.db.session import get_db
from app.models import ServiceRequest, TransactionRequest, TransactionType
from app.services.member_services import create_ip_service_request
from app.services.rates import latest_rates
from app.services.transactions import create_transaction


router = APIRouter(prefix="/member")

TRANSACTION_SLUGS = {
    "send-home": TransactionType.SEND_HOME,
    "buy-usdt": TransactionType.BUY_USDT,
    "sell-usdt": TransactionType.SELL_USDT,
}


def _slug_for_type(request_type: TransactionType) -> str:
    for slug, value in TRANSACTION_SLUGS.items():
        if value == request_type:
            return slug
    return "send-home"


def _portal_closed(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="member/paused.html",
        context=context(request, error=""),
        status_code=403,
    )


@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db)):
    if not get_settings().member_portal_enabled:
        return _portal_closed(request)
    user = require_user(request, db)
    requests = (
        db.query(TransactionRequest)
        .filter(TransactionRequest.user_id == user.id)
        .order_by(TransactionRequest.created_at.desc())
        .limit(20)
        .all()
    )
    service_requests = (
        db.query(ServiceRequest)
        .filter(ServiceRequest.user_id == user.id)
        .order_by(ServiceRequest.created_at.desc())
        .limit(5)
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="member/dashboard.html",
        context=context(
            request,
            user=user,
            requests=requests,
            service_requests=service_requests,
            rates=latest_rates(db),
            error="",
        ),
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
    contact_phone: str = Form(""),
    contact_line: str = Form(""),
    usdt_network: str = Form(""),
    wallet_address: str = Form(""),
    member_note: str = Form(""),
):
    if not get_settings().member_portal_enabled:
        return _portal_closed(request)
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
        contact_phone=contact_phone.strip(),
        contact_line=contact_line.strip(),
        usdt_network=usdt_network.strip(),
        wallet_address=wallet_address.strip(),
        member_note=member_note.strip(),
    )
    return RedirectResponse("/member?created=1", status_code=303)


@router.get("/transactions/{transaction_slug}")
def transaction_form(transaction_slug: str, request: Request, db: Session = Depends(get_db)):
    if not get_settings().member_portal_enabled:
        return _portal_closed(request)
    user = require_user(request, db)
    request_type = TRANSACTION_SLUGS.get(transaction_slug)
    if not request_type:
        return RedirectResponse("/member", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="member/transaction_form.html",
        context=context(
            request,
            user=user,
            transaction_slug=transaction_slug,
            selected_type=request_type,
            rates=latest_rates(db),
            error="",
        ),
    )


@router.post("/transactions/{transaction_slug}")
def create_typed_request(
    transaction_slug: str,
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    amount_twd: str = Form(""),
    amount_usdt: str = Form(""),
    recipient_name: str = Form(""),
    recipient_bank: str = Form(""),
    recipient_account: str = Form(""),
    contact_phone: str = Form(""),
    contact_line: str = Form(""),
    usdt_network: str = Form(""),
    wallet_address: str = Form(""),
    member_note: str = Form(""),
):
    if not get_settings().member_portal_enabled:
        return _portal_closed(request)
    verify_csrf(request, csrf_token)
    user = require_user(request, db)
    request_type = TRANSACTION_SLUGS.get(transaction_slug)
    if not request_type:
        return RedirectResponse("/member", status_code=303)
    try:
        parsed_twd = Decimal(amount_twd) if amount_twd.strip() else None
        parsed_usdt = Decimal(amount_usdt) if amount_usdt.strip() else None
    except InvalidOperation:
        return RedirectResponse(f"/member/transactions/{transaction_slug}?error=invalid_amount", status_code=303)
    if request_type in {TransactionType.SEND_HOME, TransactionType.BUY_USDT} and (not parsed_twd or parsed_twd <= 0):
        return RedirectResponse(f"/member/transactions/{transaction_slug}?error=invalid_amount", status_code=303)
    if request_type == TransactionType.SELL_USDT and (not parsed_usdt or parsed_usdt <= 0):
        return RedirectResponse(f"/member/transactions/{transaction_slug}?error=invalid_amount", status_code=303)

    create_transaction(
        db,
        user=user,
        request_type=request_type,
        amount_twd=parsed_twd,
        amount_usdt=parsed_usdt,
        recipient_name=recipient_name.strip(),
        recipient_bank=recipient_bank.strip(),
        recipient_account=recipient_account.strip(),
        contact_phone=contact_phone.strip(),
        contact_line=contact_line.strip(),
        usdt_network=usdt_network.strip(),
        wallet_address=wallet_address.strip(),
        member_note=member_note.strip(),
    )
    return RedirectResponse("/member?created=1", status_code=303)


@router.get("/services")
def services_page(request: Request, db: Session = Depends(get_db)):
    if not get_settings().member_portal_enabled:
        return _portal_closed(request)
    user = require_user(request, db)
    service_requests = (
        db.query(ServiceRequest)
        .filter(ServiceRequest.user_id == user.id)
        .order_by(ServiceRequest.created_at.desc())
        .limit(20)
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="member/services.html",
        context=context(request, user=user, service_requests=service_requests, error=""),
    )


@router.post("/services/ip-switch")
def create_ip_switch_service(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    target_region: str = Form(...),
    protocol: str = Form("recommended"),
    duration_hours: str = Form("24"),
    device_label: str = Form(""),
    current_ip: str = Form(""),
    member_note: str = Form(""),
):
    if not get_settings().member_portal_enabled:
        return _portal_closed(request)
    verify_csrf(request, csrf_token)
    user = require_user(request, db)
    try:
        parsed_hours = int(duration_hours)
    except ValueError:
        return RedirectResponse("/member/services?error=invalid_duration", status_code=303)
    create_ip_service_request(
        db,
        user=user,
        target_region=target_region,
        protocol=protocol,
        duration_hours=parsed_hours,
        device_label=device_label,
        current_ip=current_ip,
        member_note=member_note,
    )
    return RedirectResponse("/member/services?created=1", status_code=303)


@router.get("/services/ip-switch/download")
def download_ip_connector(request: Request, db: Session = Depends(get_db)):
    if not get_settings().member_portal_enabled:
        return _portal_closed(request)
    user = require_user(request, db)
    dashboard_url = str(request.url_for("services_page"))
    script = f"""# Guilua IP Connector for Windows
# Member: {user.email}
# This helper opens the Guilua service dashboard and shows the current public IP.
# Actual VPN/proxy connection details are issued by admin after approval.

$ErrorActionPreference = "Stop"
Write-Host "Guilua IP Connector" -ForegroundColor Cyan
Write-Host "Opening member service dashboard..."
Start-Process "{dashboard_url}?lang={user.locale or 'vi'}"

try {{
  $ip = Invoke-RestMethod -Uri "https://api.ipify.org?format=json" -TimeoutSec 10
  Write-Host ("Current public IP: " + $ip.ip) -ForegroundColor Green
}} catch {{
  Write-Host "Could not read current public IP. Please check your network." -ForegroundColor Yellow
}}

Write-Host ""
Write-Host "After admin approves your request, copy the endpoint from Guilua and configure your VPN/proxy client."
Read-Host "Press Enter to close"
"""
    readme = f"""Guilua IP Connector

Member: {user.email}

How to use:
1. Run guilua-ip-connector.ps1 on Windows PowerShell.
2. The script opens your Guilua member service dashboard.
3. Create or review a random IP request.
4. After admin approval, copy the issued endpoint from Guilua.

Security:
- This bundle does not contain provider API keys.
- VPN/proxy credentials are issued only after admin approval.
- Do not share your issued endpoint with other users.
"""
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("guilua-ip-connector.ps1", script)
        archive.writestr("README.txt", readme)
    buffer.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="guilua-ip-connector.zip"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)
