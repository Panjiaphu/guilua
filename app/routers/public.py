from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import resolve_locale
from app.core.templates import context, templates
from app.db.session import get_db
from app.services.crypto_market import get_crypto_market_snapshot
from app.services.rates import latest_rates


router = APIRouter()


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request=request, name="home.html", context=context(request, rates=latest_rates(db)))


@router.get("/crypto")
def crypto(request: Request):
    locale = resolve_locale(request)
    snapshot = get_crypto_market_snapshot()
    tradingview_locale = "zh_TW" if locale == "zh-TW" else "vi_VN"
    chart_config = {
        "autosize": True,
        "symbol": "BINANCE:BTCUSDT",
        "interval": "240",
        "timezone": "Asia/Taipei",
        "theme": "dark",
        "style": "1",
        "locale": tradingview_locale,
        "allow_symbol_change": True,
        "calendar": False,
        "support_host": "https://www.tradingview.com",
        "watchlist": snapshot["top_chart_symbols"],
    }
    ticker_config = {
        "symbols": [
            {"proName": item["symbol"], "title": item["name_vi" if locale == "vi" else "name_zh"]}
            for item in snapshot["macro"]
        ]
        + [{"proName": symbol, "title": symbol.replace("BINANCE:", "").replace("USDT", "")} for symbol in snapshot["top_chart_symbols"][:8]],
        "showSymbolLogo": True,
        "isTransparent": True,
        "displayMode": "adaptive",
        "colorTheme": "dark",
        "locale": tradingview_locale,
    }
    return templates.TemplateResponse(
        request=request,
        name="crypto.html",
        context=context(
            request,
            market=snapshot,
            chart_config=chart_config,
            ticker_config=ticker_config,
        ),
    )


@router.get("/ads.txt", response_class=PlainTextResponse)
def ads_txt():
    settings = get_settings()
    publisher_id = (settings.google_adsense_publisher_id or "").strip()
    if not publisher_id and settings.google_adsense_client:
        publisher_id = settings.google_adsense_client.strip().removeprefix("ca-")
    if not publisher_id:
        return "# Google AdSense is not configured for this deployment.\n"
    return f"google.com, {publisher_id}, DIRECT, f08c47fec0942fa0\n"
