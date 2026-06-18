from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.core.config import BASE_DIR, get_settings
from app.core.i18n import resolve_locale, t


templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def context(request: Request, **extra):
    locale = resolve_locale(request)
    base = {
        "request": request,
        "settings": get_settings(),
        "locale": locale,
        "csrf_token": request.state.session.get("csrf_token", ""),
        "t": lambda key: t(locale, key),
    }
    base.update(extra)
    return base
