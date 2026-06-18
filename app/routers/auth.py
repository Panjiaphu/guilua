from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

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
from app.core.templates import context, templates
from app.db.session import get_db
from app.models import User
from app.services.email import queue_email


router = APIRouter()


@router.get("/register")
def register_form(request: Request):
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
    verify_csrf(request, csrf_token)
    normalized_email = email.strip().lower()
    if len(password) < 10:
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context=context(request, error="Password must be at least 10 characters"),
        )
    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing:
        return templates.TemplateResponse(request=request, name="auth/register.html", context=context(request, error="Email already exists"))
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
        "Verify your Guilua email",
        f"Open this link to verify your email: {verify_url}",
        "email_verification",
        user=user,
    )
    login_user(request, user)
    return RedirectResponse("/member?registered=1", status_code=303)


@router.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    if get_current_user(request, db):
        return RedirectResponse("/member", status_code=303)
    return templates.TemplateResponse(request=request, name="auth/login.html", context=context(request, error=""))


@router.post("/login")
def login(
    request: Request,
    db: Session = Depends(get_db),
    csrf_token: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    verify_csrf(request, csrf_token)
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request=request, name="auth/login.html", context=context(request, error="Invalid email or password"))
    if not user.is_active:
        return templates.TemplateResponse(request=request, name="auth/login.html", context=context(request, error="Account is disabled"))
    login_user(request, user)
    return RedirectResponse("/member", status_code=303)


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
