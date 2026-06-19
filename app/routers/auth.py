from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_email_token,
    get_current_user,
    hash_password,
    login_user,
    logout_user,
    read_email_token,
    verify_csrf,
    verify_password,
)
from app.core.i18n import resolve_locale, t
from app.core.templates import context, templates
from app.db.session import get_db
from app.models import User
from app.services.email import queue_email


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
    if get_current_user(request, db):
        return RedirectResponse(next_url, status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context=context(request, error="", next_url=next_url),
    )


@router.post("/login")
def login(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    next_url: str = Form("/member"),
):
    verify_csrf(request, csrf_token)
    redirect_to = _safe_next(next_url)
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context=context(request, error=_message(request, "error.invalid_login"), next_url=redirect_to),
        )
    if not user.is_active:
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context=context(request, error=_message(request, "error.account_disabled"), next_url=redirect_to),
        )
    login_user(request, user)
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
