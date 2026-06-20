from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_email_token,
    create_password_reset_token,
    get_current_user,
    hash_password,
    login_user,
    logout_user,
    read_email_token,
    read_password_reset_token,
    verify_csrf,
    verify_password,
)
from app.core.i18n import resolve_locale, t
from app.core.templates import context, templates
from app.db.session import get_db
from app.models import User
from app.services.email import queue_email
from app.services.security_firewall import log_security_event


router = APIRouter()


def _message(request: Request, key: str) -> str:
    return t(resolve_locale(request), key)


def _safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/member"
    return value


@router.get("/register")
def register_form(request: Request):
    if not get_settings().member_registration_enabled:
        return templates.TemplateResponse(
            request=request,
            name="auth/register_closed.html",
            context=context(request, error=""),
            status_code=200,
        )
    return templates.TemplateResponse(request=request, name="auth/register.html", context=context(request, error=""))


@router.post("/register")
def register(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    locale: str = Form("vi"),
):
    if not get_settings().member_registration_enabled:
        return templates.TemplateResponse(
            request=request,
            name="auth/register_closed.html",
            context=context(request, error=""),
            status_code=403,
        )
    verify_csrf(request, csrf_token)
    normalized_email = email.strip().lower()
    if len(password) < 10:
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context=context(request, error=_message(request, "error.password_short")),
        )
    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing:
        return templates.TemplateResponse(
            request=request, name="auth/register.html", context=context(request, error=_message(request, "error.email_exists"))
        )
    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        locale=locale if locale in {"vi", "zh-TW"} else "vi",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_email_token(user.email)
    verify_url = str(request.url_for("verify_email")) + f"?token={token}"
    queue_email(
        db,
        user.email,
        "Guilua - xác minh email",
        f"Mở liên kết này để xác minh email Guilua: {verify_url}",
        "email_verification",
        user=user,
    )
    login_user(request, user)
    return RedirectResponse("/member?registered=1", status_code=303)


@router.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    next_url = _safe_next(request.query_params.get("next"))
    current_user = get_current_user(request, db)
    if current_user:
        return RedirectResponse("/admin" if current_user.is_admin else next_url, status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context=context(request, error="", next_url=next_url, reset_success=request.query_params.get("reset") == "1"),
    )


@router.post("/login")
def login(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    next_url: str = Form("/member"),
    remember_me: str | None = Form(None),
):
    verify_csrf(request, csrf_token)
    redirect_to = _safe_next(next_url)
    normalized_email = email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user or not verify_password(password, user.password_hash):
        log_security_event(
            db,
            request=request,
            event_type="login_failed",
            severity="medium",
            risk_score=35,
            status_code=401,
            username_or_email=normalized_email,
        )
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context=context(request, error=_message(request, "error.invalid_login"), next_url=redirect_to),
        )
    if not user.is_active:
        log_security_event(
            db,
            request=request,
            event_type="login_failed",
            severity="medium",
            risk_score=30,
            status_code=403,
            username_or_email=normalized_email,
            details={"reason": "inactive_account"},
        )
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context=context(request, error=_message(request, "error.account_disabled"), next_url=redirect_to),
        )
    login_user(request, user, remember_me=remember_me == "1")
    log_security_event(
        db,
        request=request,
        event_type="login_success",
        severity="info",
        risk_score=5,
        status_code=200,
        username_or_email=normalized_email,
        user=user,
    )
    if user.is_admin:
        return RedirectResponse("/admin", status_code=303)
    return RedirectResponse(redirect_to, status_code=303)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    logout_user(request)
    return RedirectResponse("/", status_code=303)


@router.get("/verify-email", name="verify_email")
def verify_email(token: str, db: Session = Depends(get_db)):
    email = read_email_token(token)
    user = db.query(User).filter(User.email == email).first()
    if user:
        user.is_email_verified = True
        db.commit()
    return RedirectResponse("/member?verified=1", status_code=303)


@router.get("/forgot-password")
def forgot_password_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="auth/forgot_password.html",
        context=context(request, sent=False, error=""),
    )


@router.post("/forgot-password")
def forgot_password(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    email: str = Form(...),
):
    verify_csrf(request, csrf_token)
    normalized_email = email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email, User.is_active.is_(True)).first()
    if user:
        token = create_password_reset_token(user.email)
        reset_url = str(request.url_for("reset_password_form")) + f"?token={token}"
        queue_email(
            db,
            user.email,
            "Guilua - đặt lại mật khẩu",
            f"Mở liên kết này để đặt lại mật khẩu Guilua trong thời hạn cho phép: {reset_url}",
            "password_reset",
            user=user,
        )
    return templates.TemplateResponse(
        request=request,
        name="auth/forgot_password.html",
        context=context(request, sent=True, error=""),
    )


@router.get("/reset-password", name="reset_password_form")
def reset_password_form(request: Request, token: str = ""):
    return templates.TemplateResponse(
        request=request,
        name="auth/reset_password.html",
        context=context(request, token=token, error="", reset_ok=False),
    )


@router.post("/reset-password")
def reset_password(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    token: str = Form(...),
    password: str = Form(...),
):
    verify_csrf(request, csrf_token)
    try:
        email = read_password_reset_token(token)
    except Exception:
        return templates.TemplateResponse(
            request=request,
            name="auth/reset_password.html",
            context=context(request, token=token, error=_message(request, "error.invalid_or_expired_token"), reset_ok=False),
            status_code=400,
        )
    if len(password) < 10:
        return templates.TemplateResponse(
            request=request,
            name="auth/reset_password.html",
            context=context(request, token=token, error=_message(request, "error.password_short"), reset_ok=False),
        )
    user = db.query(User).filter(User.email == email, User.is_active.is_(True)).first()
    if user:
        user.password_hash = hash_password(password)
        db.commit()
    return RedirectResponse("/login?reset=1", status_code=303)
