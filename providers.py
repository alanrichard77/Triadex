import os
import math
import time
import httpx
import yfinance as yf
from cachetools import TTLCache
from typing import Optional, Dict, Any, Tuple

from schemas import (
    ResolvedSymbol, QuotePrice, QuoteOutPrice, QuoteOutMarketCap,
    QuoteOutStatus, QuoteOutVolume, QuoteInternal
)

# Cache simples em memória
_CACHE = TTLCache(maxsize=2048, ttl=30)  # 30s intraday

BRAPI_URL = "https://brapi.dev/api/quote/{symbol}"
BRAPI_TIMEOUT = float(os.getenv("BRAPI_TIMEOUT", "2.5"))
YF_TIMEOUT = float(os.getenv("YF_TIMEOUT", "2.5"))

def _brl_if_b3(symbol: str) -> str:
    return "BRL" if symbol.upper().endswith(".SA") else "USD"

async def fetch_brapi(symbol: str) -> Optional[Dict[str, Any]]:
    url = BRAPI_URL.format(symbol=symbol.replace("^", ""))  # brapi não lida com ^
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
            asof=updated_at,  # brapi entrega epoch ou str, passamos adiante como veio
            source="brapi"
        ),
        market_cap=QuoteOutMarketCap(
            value=float(market_cap) if market_cap is not None else None,
            currency=currency
        ),
        volume=QuoteOutVolume(value=float(volume) if volume is not None else None),
        status=QuoteOutStatus(confidence="high", notes=[])
    )

def fetch_yahoo_sync(symbol: str) -> Optional[Dict[str, Any]]:
    # yfinance é síncrono, usamos dentro de thread interna do servidor
    t = yf.Ticker(symbol)
    info = {}
    try:
        fast = t.fast_info
        info["last"] = getattr(fast, "last_price", None)
        info["currency"] = getattr(fast, "currency", None)
        info["market_cap"] = getattr(fast, "market_cap", None)
        info["volume"] = getattr(fast, "last_volume", None)
        info["timezone"] = getattr(fast, "timezone", None)
    except Exception:
        # fallback em .info, mais lento, mas robusto
        try:
            i = t.info
            info["last"] = i.get("regularMarketPrice")
            info["currency"] = i.get("currency")
            info["market_cap"] = i.get("marketCap")
            info["volume"] = i.get("volume")
            info["timezone"] = i.get("exchangeTimezoneName")
        except Exception:
            return None
    return info

def parse_yahoo(symbol: str, data: Dict[str, Any]) -> QuoteInternal:
    currency = data.get("currency") or _brl_if_b3(symbol)
    last = data.get("last")
    market_cap = data.get("market_cap")
    volume = data.get("volume")
    # yfinance não dá change_pct direto de modo confiável, deixamos None
    return QuoteInternal(
        price=QuoteOutPrice(
            last=float(last) if last is not None else None,
            change_pct=None,
            currency=currency,
            asof=None,
            source="yahoo"
        ),
        market_cap=QuoteOutMarketCap(
            value=float(market_cap) if market_cap is not None else None,
            currency=currency
        ),
        volume=QuoteOutVolume(value=float(volume) if volume is not None else None),
        status=QuoteOutStatus(confidence="medium", notes=["Variação diária não disponível no Yahoo fast_info"])
    )

class QuoteOrchestrator:
    def __init__(self):
        self.cache = _CACHE

    async def get_quote(self, resolved: ResolvedSymbol, prefer: Optional[str] = None) -> QuoteInternal:
        cache_key = f"{resolved.symbol}:{prefer or 'auto'}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        providers = ["brapi", "yahoo"]
        if prefer in providers:
            # tenta preferida primeiro
            providers.remove(prefer)
            ordered = [prefer] + providers
        else:
            ordered = providers

        last_error = None
        for p in ordered:
            try:
                if p == "brapi":
                    data = await fetch_brapi(resolved.symbol)
                    if data:
                        parsed = parse_brapi(resolved.symbol, data)
                        self._postprocess(parsed)
                        self.cache[cache_key] = parsed
                        return parsed
                elif p == "yahoo":
                    data = fetch_yahoo_sync(resolved.symbol)
                    if data:
                        parsed = parse_yahoo(resolved.symbol, data)
                        self._postprocess(parsed)
                        self.cache[cache_key] = parsed
                        return parsed
            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(f"Todas as fontes falharam para {resolved.symbol}. {last_error or ''}")

    def _postprocess(self, q: QuoteInternal) -> None:
        # Validações simples
        if q.price.last is not None and (math.isnan(q.price.last) or q.price.last <= 0):
            q.status.notes.append("Preço inválido ou não disponível")
            q.status.confidence = "low"
        # Ajuste de moeda ausente
        if not q.price.currency:
            q.price.currency = "BRL"
            q.status.notes.append("Moeda inferida")

