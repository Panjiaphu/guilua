from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import BASE_DIR, get_settings
from app.core.i18n import resolve_locale
from app.core.security import SessionMiddleware, ensure_admin_seed
from app.db.session import Base, engine
from app.routers import admin, auth, member, public, webhooks
from app.services.rates import ensure_default_rates
from app.db.session import SessionLocal


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.add_middleware(SessionMiddleware)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
    app.include_router(public.router)
    app.include_router(auth.router)
    app.include_router(member.router)
    app.include_router(admin.router)
    app.include_router(webhooks.router)

    @app.on_event("startup")
    def startup() -> None:
        Base.metadata.create_all(bind=engine)
        ensure_admin_seed()
        with SessionLocal() as db:
            ensure_default_rates(db)

    @app.middleware("http")
    async def locale_cookie(request: Request, call_next):
        response = await call_next(request)
        locale = resolve_locale(request)
        response.set_cookie("lang", locale, max_age=60 * 60 * 24 * 365, samesite="lax")
        return response

    @app.get("/healthz/")
    def healthz():
        return {"status": "ok", "app": settings.app_name}

    @app.get("/dashboard")
    def dashboard_redirect():
        return RedirectResponse("/member", status_code=303)

    return app


app = create_app()
