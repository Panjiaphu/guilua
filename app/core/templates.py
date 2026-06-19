from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.core.config import BASE_DIR, get_settings
from app.core.i18n import resolve_locale, t


templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def _format_price(value) -> str:
    if value is None:
        return "-"
    number = float(value)
    if abs(number) >= 1000:
        return f"{number:,.2f}"
    if abs(number) >= 1:
        return f"{number:,.4f}"
    return f"{number:,.8f}".rstrip("0").rstrip(".")


def _format_compact(value) -> str:
    if value is None:
        return "-"
    number = float(value)
    abs_number = abs(number)
    if abs_number >= 1_000_000_000_000:
        return f"{number / 1_000_000_000_000:.2f}T"
    if abs_number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if abs_number >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if abs_number >= 1_000:
        return f"{number / 1_000:.2f}K"
    return _format_price(number)


def _format_percent(value) -> str:
    if value is None:
        return "-"
    return f"{float(value):+.2f}%"


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
        "service_type_label": lambda service_type: t(locale, f"service.type.{service_type}"),
        "service_region_label": lambda region: t(locale, f"service.region.{region}"),
        "service_protocol_label": lambda protocol: t(locale, f"service.protocol.{protocol}"),
        "event_label": lambda event_type: t(locale, f"event.{event_type}"),
        "email_status_label": lambda status: t(locale, f"email.status.{status.value if hasattr(status, 'value') else status}"),
        "source_label": lambda source: t(locale, f"rates.source.{source}") if source == "manual" else source,
        "pair_label": lambda pair: pair.replace("_", " -> "),
        "format_price": _format_price,
        "format_compact": _format_compact,
        "format_percent": _format_percent,
        "trend_class": lambda value: "up" if float(value or 0) >= 0 else "down",
        "admin_contact": {
            "email": settings.admin_notification_email or settings.admin_seed_email,
            "line": settings.admin_line_id,
            "phone": settings.admin_phone,
        },
    }
    base.update(extra)
    return base
