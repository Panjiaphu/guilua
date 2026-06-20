import base64
from io import BytesIO

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import resolve_locale
from app.core.security import get_current_user
from app.core.templates import context, templates
from app.db.session import get_db
from app.models import ContentPost, ContentPostStatus, ContentPostType, ShortLink, UtilityItem
from app.services.commercial import (
    create_shortlink,
    ping_public_url,
    record_utility_usage,
    validate_public_url,
)
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


def _published_posts(db: Session, post_type: ContentPostType, locale: str):
    return (
        db.query(ContentPost)
        .filter(
            ContentPost.post_type == post_type,
            ContentPost.status == ContentPostStatus.PUBLISHED,
            ContentPost.locale.in_([locale, "vi"]),
        )
        .order_by(ContentPost.sort_order.desc(), ContentPost.published_at.desc(), ContentPost.created_at.desc())
        .all()
    )


@router.get("/jobs")
def jobs(request: Request, db: Session = Depends(get_db)):
    locale = resolve_locale(request)
    return templates.TemplateResponse(
        request=request,
        name="content_list.html",
        context=context(
            request,
            page_kind="jobs",
            posts=_published_posts(db, ContentPostType.JOB, locale),
        ),
    )


@router.get("/jobs/{slug}")
def job_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    post = (
        db.query(ContentPost)
        .filter(
            ContentPost.slug == slug,
            ContentPost.post_type == ContentPostType.JOB,
            ContentPost.status == ContentPostStatus.PUBLISHED,
        )
        .first()
    )
    if not post:
        raise HTTPException(status_code=404, detail="Job post not found")
    return templates.TemplateResponse(
        request=request,
        name="content_detail.html",
        context=context(request, page_kind="jobs", post=post),
    )


@router.get("/shop")
def shop(request: Request, db: Session = Depends(get_db)):
    locale = resolve_locale(request)
    return templates.TemplateResponse(
        request=request,
        name="content_list.html",
        context=context(
            request,
            page_kind="shop",
            posts=_published_posts(db, ContentPostType.SHOP, locale),
        ),
    )


@router.get("/shop/{slug}")
def shop_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    post = (
        db.query(ContentPost)
        .filter(
            ContentPost.slug == slug,
            ContentPost.post_type == ContentPostType.SHOP,
            ContentPost.status == ContentPostStatus.PUBLISHED,
        )
        .first()
    )
    if not post:
        raise HTTPException(status_code=404, detail="Shop post not found")
    return templates.TemplateResponse(
        request=request,
        name="content_detail.html",
        context=context(request, page_kind="shop", post=post),
    )


@router.get("/utilities")
def utilities(request: Request, db: Session = Depends(get_db)):
    items = (
        db.query(UtilityItem)
        .filter(UtilityItem.is_active.is_(True))
        .order_by(UtilityItem.sort_order.asc(), UtilityItem.created_at.asc())
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="utilities.html",
        context=context(request, utilities=items),
    )


@router.get("/utilities/qr")
def qr_get(request: Request):
    return templates.TemplateResponse(request=request, name="utility_qr.html", context=context(request, qr_data_url=""))


@router.post("/utilities/qr")
def qr_post(request: Request, db: Session = Depends(get_db), payload: str = Form(...)):
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="QR dependency is not installed") from exc
    text = payload.strip()
    if not text or len(text) > 1200:
        return templates.TemplateResponse(
            request=request,
            name="utility_qr.html",
            context=context(request, qr_data_url="", error="invalid_input"),
        )
    factory = qrcode.image.svg.SvgPathImage
    image = qrcode.make(text, image_factory=factory)
    buffer = BytesIO()
    image.save(buffer)
    data_url = "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    record_utility_usage(db, get_current_user(request, db), "qr_generator")
    return templates.TemplateResponse(
        request=request,
        name="utility_qr.html",
        context=context(request, qr_data_url=data_url, payload=text),
    )


@router.get("/utilities/shortlink")
def shortlink_get(request: Request):
    return templates.TemplateResponse(request=request, name="utility_shortlink.html", context=context(request))


@router.post("/utilities/shortlink")
def shortlink_post(request: Request, db: Session = Depends(get_db), target_url: str = Form(...)):
    try:
        item = create_shortlink(db, target_url, get_current_user(request, db))
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="utility_shortlink.html",
            context=context(request, error=str(exc), target_url=target_url),
        )
    settings = get_settings()
    short_url = f"{settings.public_base_url.rstrip('/')}/s/{item.code}"
    return templates.TemplateResponse(
        request=request,
        name="utility_shortlink.html",
        context=context(request, short_url=short_url, item=item),
    )


@router.get("/s/{code}")
def shortlink_redirect(code: str, db: Session = Depends(get_db)):
    item = db.query(ShortLink).filter(ShortLink.code == code).first()
    if not item:
        raise HTTPException(status_code=404, detail="Shortlink not found")
    item.click_count += 1
    db.commit()
    return RedirectResponse(item.target_url, status_code=302)


@router.get("/utilities/ping")
def ping_get(request: Request):
    return templates.TemplateResponse(request=request, name="utility_ping.html", context=context(request))


@router.post("/utilities/ping")
def ping_post(request: Request, db: Session = Depends(get_db), target_url: str = Form(...)):
    result = ping_public_url(target_url)
    record_utility_usage(db, get_current_user(request, db), "ping_website")
    return templates.TemplateResponse(
        request=request,
        name="utility_ping.html",
        context=context(request, result=result),
    )


@router.get("/utilities/free-vpn")
def free_vpn(request: Request):
    return templates.TemplateResponse(request=request, name="utility_free_vpn.html", context=context(request))


@router.get("/advertising")
def advertising(request: Request):
    return templates.TemplateResponse(request=request, name="contact_page.html", context=context(request, page_kind="advertising"))


@router.get("/build-idea")
def build_idea(request: Request):
    return templates.TemplateResponse(request=request, name="contact_page.html", context=context(request, page_kind="build_idea"))
