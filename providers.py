import os
import math
import httpx
import yfinance as yf
from cachetools import TTLCache
from typing import Optional, Dict, Any

from schemas import (
    ResolvedSymbol, QuoteOutPrice, QuoteOutMarketCap,
    QuoteOutStatus, QuoteOutVolume, QuoteInternal
)

# Cache simples em memória (TTL 30s)
_CACHE = TTLCache(maxsize=2048, ttl=30)

BRAPI_URL = "https://brapi.dev/api/quote/{symbol}"
BRAPI_TIMEOUT = float(os.getenv("BRAPI_TIMEOUT", "2.5"))
YF_TIMEOUT = float(os.getenv("YF_TIMEOUT", "2.5"))


def _brl_if_b3(symbol: str) -> str:
    """Define BRL se for símbolo da B3 (.SA)."""
    return "BRL" if symbol.upper().endswith(".SA") else "USD"


# =============== BRAPI ===============
async def fetch_brapi(symbol: str) -> Optional[Dict[str, Any]]:
    """Busca dados de cotação na API da Brapi."""
    url = BRAPI_URL.format(symbol=symbol.replace("^", ""))
    params = {"range": "1d"}

    async with httpx.AsyncClient(timeout=BRAPI_TIMEOUT) as client:
        r = await client.get(url, params=params)
        if r.status_code != 200:
            return None

        data = r.json()
        if not data or "results" not in data or not data["results"]:
            return None

        return data["results"][0]


def parse_brapi(symbol: str, data: Dict[str, Any]) -> QuoteInternal:
    """Normaliza a resposta da Brapi."""
    last = data.get("regularMarketPrice") or data.get("close") or data.get("price")
    change_pct = data.get("regularMarketChangePercent") or data.get("changePercent")
    currency = data.get("currency") or _brl_if_b3(symbol)
    market_cap = data.get("marketCap")
    volume = data.get("regularMarketVolume") or data.get("volume")
    updated_at = data.get("regularMarketTime") or data.get("updatedAt")

    return QuoteInternal(
        price=QuoteOutPrice(
            last=float(last) if last is not None else None,
            change_pct=float(change_pct) if change_pct is not None else None,
            currency=currency,
            asof=str(updated_at),
            source="brapi"
        ),
        market_cap=QuoteOutMarketCap(
            value=float(market_cap) if market_cap is not None else None,
            currency=currency
        ),
        volume=QuoteOutVolume(value=float(volume) if volume is not None else None),
        status=QuoteOutStatus(confidence="high", notes=[])
    )


# =============== YAHOO FINANCE ===============
def fetch_yahoo_sync(symbol: str) -> Optional[Dict[str, Any]]:
    """Busca dados via yfinance (modo síncrono)."""
    t = yf.Ticker(symbol)
    info = {}

    try:
        fast = t.fast_info
        info["last"] = getattr(fast, "last_price", None)
        info["currency"] = getattr(fast, "currency", None)
        info["market_cap"] = getattr(fast, "market_cap", None)
        info["volume"] = getattr(fast, "last_volume", None)
    except Exception:
        try:
            i = t.info
            info["last"] = i.get("regularMarketPrice")
            info["currency"] = i.get("currency")
            info["market_cap"] = i.get("marketCap")
            info["volume"] = i.get("volume")
        except Exception:
            return None

    return info


def parse_yahoo(symbol: str, data: Dict[str, Any]) -> QuoteInternal:
    """Normaliza dados do Yahoo Finance."""
    currency = data.get("currency") or _brl_if_b3(symbol)
    last = data.get("last")
    market_cap = data.get("market_cap")
    volume = data.get("volume")

    return QuoteInternal(
        price=QuoteOutPrice(
            last=float(last) if last is not None else None,
            change_pct=None,  # Yahoo nem sempre entrega variação diária
            currency=currency,
            asof=None,
            source="yahoo"
        ),
        market_cap=QuoteOutMarketCap(
            value=float(market_cap) if market_cap is not None else None,
            currency=currency
        ),
        volume=QuoteOutVolume(value=float(volume) if volume is not None else None),
        status=QuoteOutStatus(
            confidence="medium",
            notes=["Variação diária não disponível no Yahoo"]
        )
    )


#
