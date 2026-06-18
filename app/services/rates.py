from decimal import Decimal
import json
from urllib.request import urlopen

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ExchangeRate


DEFAULT_RATES = {
    "TWD_VND": (Decimal("805.50"), Decimal("805.50")),
    "USDT_TWD": (Decimal("32.10"), Decimal("32.45")),
}


def ensure_default_rates(db: Session) -> None:
    for pair, (buy_rate, sell_rate) in DEFAULT_RATES.items():
        existing = db.query(ExchangeRate).filter(ExchangeRate.pair == pair).order_by(ExchangeRate.id.desc()).first()
        if existing:
            continue
        db.add(
            ExchangeRate(
                pair=pair,
                buy_rate=buy_rate,
                sell_rate=sell_rate,
                source="manual",
                is_manual=True,
                note="Manual fallback",
            )
        )
    db.commit()


def latest_rates(db: Session) -> dict[str, ExchangeRate]:
    ensure_default_rates(db)
    result: dict[str, ExchangeRate] = {}
    for pair in DEFAULT_RATES:
        result[pair] = db.query(ExchangeRate).filter(ExchangeRate.pair == pair).order_by(ExchangeRate.id.desc()).first()
    return result


def update_manual_rate(db: Session, pair: str, buy_rate: Decimal, sell_rate: Decimal, note: str = "") -> ExchangeRate:
    item = ExchangeRate(pair=pair, buy_rate=buy_rate, sell_rate=sell_rate, source="manual", is_manual=True, note=note)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def fetch_live_rates() -> dict[str, tuple[Decimal, Decimal]]:
    settings = get_settings()
    if not settings.exchange_rate_provider_url:
        return {}
    with urlopen(settings.exchange_rate_provider_url, timeout=settings.live_rate_timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rates: dict[str, tuple[Decimal, Decimal]] = {}
    for pair, data in payload.items():
        rates[pair] = (Decimal(str(data["buy_rate"])), Decimal(str(data["sell_rate"])))
    return rates
