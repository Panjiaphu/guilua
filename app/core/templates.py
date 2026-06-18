from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.core.config import BASE_DIR, get_settings
from app.core.i18n import resolve_locale, t


templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def context(request: Request, **extra):
    locale = resolve_locale(request)
    settings = get_settings()
    base = {
        "request": request,
        "settings": settings,
        "locale": locale,
        "csrf_token": request.state.session.get("csrf_token", ""),
        "t": lambda key: t(locale, key),
        "status_label": lambda status: t(locale, f"status.{status.value if hasattr(status, 'value') else status}"),
        "type_label": lambda request_type: t(
            locale, f"type.{request_type.value if hasattr(request_type, 'value') else request_type}"
        ),
        "event_label": lambda event_type: t(locale, f"event.{event_type}"),
        "email_status_label": lambda status: t(locale, f"email.status.{status.value if hasattr(status, 'value') else status}"),
        "source_label": lambda source: t(locale, f"rates.source.{source}") if source == "manual" else source,
        "pair_label": lambda pair: pair.replace("_", " -> "),
        "admin_contact": {
            "email": settings.admin_notification_email or settings.admin_seed_email,
            "line": settings.admin_line_id,
            "phone": settings.admin_phone,
        },
    }
    base.update(extra)
    return base
