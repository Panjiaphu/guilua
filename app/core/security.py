import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.hash import pbkdf2_sha256
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import User


settings = get_settings()
serializer = URLSafeTimedSerializer(settings.secret_key, salt="guilua-session")
email_serializer = URLSafeTimedSerializer(settings.secret_key, salt="guilua-email")
password_reset_serializer = URLSafeTimedSerializer(settings.secret_key, salt="guilua-password-reset")
MIN_ADMIN_SEED_PASSWORD_LENGTH = 14


def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pbkdf2_sha256.verify(password, password_hash)


def create_email_token(email: str) -> str:
    return email_serializer.dumps({"email": email})


def read_email_token(token: str, max_age_seconds: int = 60 * 60 * 24) -> str:
    try:
        payload = email_serializer.loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token") from exc
    return str(payload["email"])


def create_password_reset_token(email: str) -> str:
    return password_reset_serializer.dumps({"email": email})


def read_password_reset_token(token: str) -> str:
    try:
        payload = password_reset_serializer.loads(token, max_age=get_settings().password_reset_token_max_age_seconds)
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token") from exc
    return str(payload["email"])


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        request.state.session = self._load_session(request)
        request.state.session.setdefault("csrf_token", secrets.token_urlsafe(24))
        response = await call_next(request)
        if request.state.session.get("_clear"):
            response.delete_cookie(settings.session_cookie_name)
            return response
        cookie_value = serializer.dumps(request.state.session)
        max_age = int(request.state.session.get("_max_age_seconds") or settings.session_max_age_seconds)
        response.set_cookie(
            settings.session_cookie_name,
            cookie_value,
            max_age=max_age,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite="lax",
        )
        return response

    @staticmethod
    def _load_session(request: Request) -> dict[str, Any]:
        raw_cookie = request.cookies.get(settings.session_cookie_name)
        if not raw_cookie:
            return {}
        try:
            max_age = max(settings.session_max_age_seconds, settings.session_remember_max_age_seconds)
            data = serializer.loads(raw_cookie, max_age=max_age)
        except (BadSignature, SignatureExpired):
            return {}
        return data if isinstance(data, dict) else {}


def login_user(request: Request, user: User, remember_me: bool = False) -> None:
    request.state.session["user_id"] = user.id
    request.state.session["csrf_token"] = secrets.token_urlsafe(24)
    request.state.session["_max_age_seconds"] = (
        settings.session_remember_max_age_seconds if remember_me else settings.session_max_age_seconds
    )


def logout_user(request: Request) -> None:
    request.state.session.clear()
    request.state.session["_clear"] = True


def verify_csrf(request: Request, token: str) -> None:
    if not token or token != request.state.session.get("csrf_token"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def get_current_user(request: Request, db: Session) -> User | None:
    user_id = request.state.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, int(user_id))


def require_user(request: Request, db: Session) -> User:
    user = get_current_user(request, db)
    if not user or not user.is_active:
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={quote(path, safe='/?=&-_%.')}"},
        )
    return user


def require_admin(request: Request, db: Session) -> User:
    user = require_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def ensure_admin_seed() -> None:
    settings = get_settings()
    admin_email = settings.admin_seed_email.strip().lower()
    with SessionLocal() as db:
        existing = db.query(User).filter(User.is_admin.is_(True)).first()
        if existing:
            return
        password = settings.admin_seed_password
        if settings.is_production:
            if not password:
                raise RuntimeError("ADMIN_SEED_PASSWORD is required before seeding the first production admin.")
            if len(password) < MIN_ADMIN_SEED_PASSWORD_LENGTH:
                raise RuntimeError(
                    "ADMIN_SEED_PASSWORD must be at least 14 characters before seeding the first production admin."
                )
        password = password or secrets.token_urlsafe(18)
        admin = User(
            email=admin_email,
            password_hash=hash_password(password),
            full_name="Guilua Admin",
            locale="vi",
            is_admin=True,
            is_email_verified=True,
        )
        db.add(admin)
        db.commit()
