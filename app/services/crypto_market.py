from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class CoinDefinition:
    symbol: str
    name: str
    coingecko_id: str
    binance_symbol: str | None = None


@dataclass(frozen=True)
class MarketGroup:
    key: str
    name_vi: str
    name_zh: str
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class MacroSymbol:
    key: str
    name_vi: str
    name_zh: str
    symbol: str
    role_vi: str
    role_zh: str


COINS: tuple[CoinDefinition, ...] = (
    CoinDefinition("BTC", "Bitcoin", "bitcoin", "BTCUSDT"),
    CoinDefinition("ETH", "Ethereum", "ethereum", "ETHUSDT"),
    CoinDefinition("BNB", "BNB", "binancecoin", "BNBUSDT"),
    CoinDefinition("SOL", "Solana", "solana", "SOLUSDT"),
    CoinDefinition("XRP", "XRP", "ripple", "XRPUSDT"),
    CoinDefinition("DOGE", "Dogecoin", "dogecoin", "DOGEUSDT"),
    CoinDefinition("ADA", "Cardano", "cardano", "ADAUSDT"),
    CoinDefinition("AVAX", "Avalanche", "avalanche-2", "AVAXUSDT"),
    CoinDefinition("LINK", "Chainlink", "chainlink", "LINKUSDT"),
    CoinDefinition("TRX", "TRON", "tron", "TRXUSDT"),
    CoinDefinition("TON", "Toncoin", "the-open-network", "TONUSDT"),
    CoinDefinition("DOT", "Polkadot", "polkadot", "DOTUSDT"),
    CoinDefinition("SUI", "Sui", "sui", "SUIUSDT"),
    CoinDefinition("APT", "Aptos", "aptos", "APTUSDT"),
    CoinDefinition("NEAR", "NEAR Protocol", "near", "NEARUSDT"),
    CoinDefinition("ARB", "Arbitrum", "arbitrum", "ARBUSDT"),
    CoinDefinition("OP", "Optimism", "optimism", "OPUSDT"),
    CoinDefinition("POL", "Polygon", "polygon-ecosystem-token", "POLUSDT"),
    CoinDefinition("STRK", "Starknet", "starknet", "STRKUSDT"),
    CoinDefinition("IMX", "Immutable", "immutable-x", "IMXUSDT"),
    CoinDefinition("UNI", "Uniswap", "uniswap", "UNIUSDT"),
    CoinDefinition("AAVE", "Aave", "aave", "AAVEUSDT"),
    CoinDefinition("MKR", "Maker", "maker", "MKRUSDT"),
    CoinDefinition("LDO", "Lido DAO", "lido-dao", "LDOUSDT"),
    CoinDefinition("CRV", "Curve DAO", "curve-dao-token", "CRVUSDT"),
    CoinDefinition("SNX", "Synthetix", "havven", "SNXUSDT"),
    CoinDefinition("RUNE", "THORChain", "thorchain", "RUNEUSDT"),
    CoinDefinition("FET", "Fetch.ai", "fetch-ai", "FETUSDT"),
    CoinDefinition("RENDER", "Render", "render-token", "RENDERUSDT"),
    CoinDefinition("ICP", "Internet Computer", "internet-computer", "ICPUSDT"),
    CoinDefinition("GRT", "The Graph", "the-graph", "GRTUSDT"),
    CoinDefinition("ONDO", "Ondo", "ondo-finance", "ONDOUSDT"),
    CoinDefinition("PENDLE", "Pendle", "pendle", "PENDLEUSDT"),
    CoinDefinition("SHIB", "Shiba Inu", "shiba-inu", "SHIBUSDT"),
    CoinDefinition("PEPE", "Pepe", "pepe", "PEPEUSDT"),
    CoinDefinition("BONK", "Bonk", "bonk", "BONKUSDT"),
    CoinDefinition("FLOKI", "Floki", "floki", "FLOKIUSDT"),
    CoinDefinition("WIF", "dogwifhat", "dogwifcoin", "WIFUSDT"),
    CoinDefinition("GALA", "GALA", "gala", "GALAUSDT"),
    CoinDefinition("SAND", "The Sandbox", "the-sandbox", "SANDUSDT"),
    CoinDefinition("MANA", "Decentraland", "decentraland", "MANAUSDT"),
    CoinDefinition("AXS", "Axie Infinity", "axie-infinity", "AXSUSDT"),
    CoinDefinition("PYTH", "Pyth Network", "pyth-network", "PYTHUSDT"),
    CoinDefinition("API3", "API3", "api3", "API3USDT"),
    CoinDefinition("BAND", "Band Protocol", "band-protocol", "BANDUSDT"),
    CoinDefinition("STX", "Stacks", "blockstack", "STXUSDT"),
    CoinDefinition("ORDI", "Ordinals", "ordinals", "ORDIUSDT"),
    CoinDefinition("JUP", "Jupiter", "jupiter-exchange-solana", "JUPUSDT"),
    CoinDefinition("JTO", "Jito", "jito-governance-token", "JTOUSDT"),
    CoinDefinition("USDT", "Tether", "tether", "USDTUSDC"),
    CoinDefinition("USDC", "USD Coin", "usd-coin", "USDCUSDT"),
    CoinDefinition("DAI", "Dai", "dai", "DAIUSDT"),
    CoinDefinition("FDUSD", "First Digital USD", "first-digital-usd", "FDUSDUSDT"),
)


MARKET_GROUPS: tuple[MarketGroup, ...] = (
    MarketGroup("l1", "Layer 1", "Layer 1", ("BTC", "ETH", "SOL", "BNB", "ADA", "AVAX", "SUI", "APT")),
    MarketGroup("l2", "Layer 2", "Layer 2", ("ARB", "OP", "POL", "STRK", "IMX")),
    MarketGroup("defi", "DeFi", "DeFi", ("UNI", "AAVE", "MKR", "LDO", "CRV", "SNX", "RUNE")),
    MarketGroup("ai", "AI", "AI", ("FET", "RENDER", "ICP", "GRT", "NEAR")),
    MarketGroup("rwa", "RWA", "RWA", ("ONDO", "PENDLE", "MKR", "LINK")),
    MarketGroup("meme", "Meme", "Meme", ("DOGE", "SHIB", "PEPE", "BONK", "FLOKI", "WIF")),
    MarketGroup("gaming", "Gaming", "遊戲", ("IMX", "GALA", "SAND", "MANA", "AXS")),
    MarketGroup("oracle", "Oracle", "預言機", ("LINK", "PYTH", "API3", "BAND")),
    MarketGroup("btc_eco", "BTC Ecosystem", "BTC 生態", ("BTC", "STX", "ORDI", "RUNE")),
    MarketGroup("sol_eco", "SOL Ecosystem", "SOL 生態", ("SOL", "JUP", "JTO", "PYTH", "BONK", "WIF")),
    MarketGroup("exchange", "Exchange", "交易平台", ("BNB", "UNI", "RUNE", "JUP")),
    MarketGroup("stablecoin", "Stablecoin", "穩定幣", ("USDT", "USDC", "DAI", "FDUSD")),
)


MACRO_SYMBOLS: tuple[MacroSymbol, ...] = (
    MacroSymbol("gold", "Giá vàng", "黃金", "OANDA:XAUUSD", "Thanh khoản phòng thủ", "防禦流動性"),
    MacroSymbol("oil", "Giá dầu", "原油", "TVC:USOIL", "Tín hiệu lạm phát", "通膨訊號"),
    MacroSymbol("btc_d", "BTC.D", "BTC.D", "CRYPTOCAP:BTC.D", "Dominance Bitcoin", "比特幣市佔"),
    MacroSymbol("eth_d", "ETH.D", "ETH.D", "CRYPTOCAP:ETH.D", "Dominance Ethereum", "以太坊市佔"),
    MacroSymbol("total", "TOTAL 1", "TOTAL 1", "CRYPTOCAP:TOTAL", "Tổng vốn hóa crypto", "加密總市值"),
    MacroSymbol("total2", "TOTAL 2", "TOTAL 2", "CRYPTOCAP:TOTAL2", "Altcoin excluding BTC", "排除 BTC"),
    MacroSymbol("total3", "TOTAL 3", "TOTAL 3", "CRYPTOCAP:TOTAL3", "Altcoin excluding BTC/ETH", "排除 BTC/ETH"),
    MacroSymbol("total_defi", "TOTAL DeFi", "TOTAL DeFi", "CRYPTOCAP:TOTALDEFI", "Vốn hóa DeFi", "DeFi 市值"),
    MacroSymbol("usdt_d", "USDT.D", "USDT.D", "CRYPTOCAP:USDT.D", "Dòng tiền stablecoin", "穩定幣流向"),
    MacroSymbol("dxy", "DXY", "DXY", "TVC:DXY", "Dollar index", "美元指數"),
)


FALLBACK_PRICES: dict[str, float] = {
    "BTC": 65000.0,
    "ETH": 3200.0,
    "BNB": 580.0,
    "SOL": 145.0,
    "XRP": 0.52,
    "DOGE": 0.12,
    "ADA": 0.44,
    "AVAX": 28.0,
    "LINK": 14.0,
    "TRX": 0.12,
    "TON": 6.3,
    "DOT": 6.1,
}


_CACHE: tuple[float, dict[str, Any]] | None = None


def get_crypto_market_snapshot(force_refresh: bool = False) -> dict[str, Any]:
    global _CACHE
    settings = get_settings()
    now_monotonic = monotonic()
    if not force_refresh and _CACHE and now_monotonic - _CACHE[0] < settings.crypto_market_cache_seconds:
        return _CACHE[1]

    coingecko_data: dict[str, Any] = {}
    binance_data: dict[str, Any] = {}
    errors: list[str] = []

    if settings.crypto_market_live_enabled:
        try:
            coingecko_data = _fetch_coingecko(settings)
        except Exception as exc:  # noqa: BLE001 - public dashboard must keep rendering
            errors.append(f"CoinGecko: {exc}")
        try:
            binance_data = _fetch_binance(settings)
        except Exception as exc:  # noqa: BLE001 - public dashboard must keep rendering
            errors.append(f"Binance: {exc}")

    coins = _build_coin_rows(coingecko_data, binance_data)
    coin_map = {item["symbol"]: item for item in coins}
    snapshot = {
        "coins": coins,
        "coin_map": coin_map,
        "groups": _build_group_rows(coin_map),
        "macro": [symbol.__dict__ for symbol in MACRO_SYMBOLS],
        "tradingview_symbols": [symbol.symbol for symbol in MACRO_SYMBOLS]
        + [f"BINANCE:{coin.binance_symbol}" for coin in COINS[:12] if coin.binance_symbol],
        "top_chart_symbols": [f"BINANCE:{coin.binance_symbol}" for coin in COINS[:12] if coin.binance_symbol],
        "source_status": _source_status(coingecko_data, binance_data, errors),
        "errors": errors,
        "updated_at": datetime.now(timezone.utc),
    }

    _CACHE = (now_monotonic, snapshot)
    return snapshot


def clear_crypto_market_cache() -> None:
    global _CACHE
    _CACHE = None


def _fetch_coingecko(settings) -> dict[str, Any]:
    ids = ",".join(coin.coingecko_id for coin in COINS)
    params = {
        "ids": ids,
        "vs_currencies": "usd",
        "include_market_cap": "true",
        "include_24hr_vol": "true",
        "include_24hr_change": "true",
        "precision": "full",
    }
    headers = {"accept": "application/json"}
    if settings.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_api_key
    with httpx.Client(timeout=settings.crypto_market_timeout_seconds) as client:
        response = client.get(settings.coingecko_api_url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
    return data if isinstance(data, dict) else {}


def _fetch_binance(settings) -> dict[str, Any]:
    with httpx.Client(timeout=settings.crypto_market_timeout_seconds) as client:
        response = client.get(settings.binance_api_url)
        response.raise_for_status()
        data = response.json()
    rows = data if isinstance(data, list) else [data]
    return {str(item.get("symbol", "")).upper(): item for item in rows if isinstance(item, dict)}


def _build_coin_rows(coingecko_data: dict[str, Any], binance_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for coin in COINS:
        cg = coingecko_data.get(coin.coingecko_id, {}) if coingecko_data else {}
        bn = binance_data.get(coin.binance_symbol or "", {}) if coin.binance_symbol else {}
        price = _as_float(bn.get("lastPrice")) or _as_float(cg.get("usd")) or FALLBACK_PRICES.get(coin.symbol, 0.0)
        change = _as_float(bn.get("priceChangePercent")) or _as_float(cg.get("usd_24h_change")) or 0.0
        market_cap = _as_float(cg.get("usd_market_cap"))
        volume = _as_float(bn.get("quoteVolume")) or _as_float(cg.get("usd_24h_vol"))
        source = "Binance + CoinGecko" if bn and cg else "Binance" if bn else "CoinGecko" if cg else "fallback"
        rows.append(
            {
                "symbol": coin.symbol,
                "name": coin.name,
                "price": price,
                "change_24h": change,
                "market_cap": market_cap,
                "volume_24h": volume,
                "source": source,
                "tradingview_symbol": f"BINANCE:{coin.binance_symbol}" if coin.binance_symbol else "",
            }
        )
    return rows


def _build_group_rows(coin_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    groups = []
    for group in MARKET_GROUPS:
        members = [coin_map[symbol] for symbol in group.symbols if symbol in coin_map]
        changes = [member["change_24h"] for member in members if member.get("change_24h") is not None]
        avg_change = sum(changes) / len(changes) if changes else 0.0
        leaders = sorted(members, key=lambda item: item.get("change_24h") or 0.0, reverse=True)[:3]
        groups.append(
            {
                "key": group.key,
                "name_vi": group.name_vi,
                "name_zh": group.name_zh,
                "symbols": group.symbols,
                "avg_change_24h": avg_change,
                "leaders": leaders,
                "members": members,
            }
        )
    return groups


def _source_status(coingecko_data: dict[str, Any], binance_data: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    live_sources = []
    if coingecko_data:
        live_sources.append("CoinGecko")
    if binance_data:
        live_sources.append("Binance")
    return {
        "is_live": bool(live_sources),
        "label": " + ".join(live_sources) if live_sources else "Fallback",
        "error_count": len(errors),
    }


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
