import os
import math
import csv
import io
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import httpx
import yfinance as yf
from cachetools import TTLCache

from schemas import (
    ResolvedSymbol, QuoteOutPrice, QuoteOutMarketCap,
    QuoteOutStatus, QuoteOutVolume, QuoteInternal
)

# =========================
# Config & Cache
# =========================
_CACHE = TTLCache(maxsize=4096, ttl=int(os.getenv("CACHE_TTL", "30")))

BRAPI_URL = "https://brapi.dev/api/quote/{symbol}"
BRAPI_TIMEOUT = float(os.getenv("BRAPI_TIMEOUT", "2.0"))
YF_TIMEOUT = float(os.getenv("YF_TIMEOUT", "2.5"))
STOOQ_TIMEOUT = float(os.getenv("STOOQ_TIMEOUT", "2.0"))
BRAPI_TOKEN = os.getenv("BRAPI_TOKEN", "").strip()

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Triadex/1.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _is_b3(symbol: str) -> bool:
    return symbol.upper().endswith(".SA")

def _ccy(symbol: str) -> str:
    return "BRL" if _is_b3(symbol) else "USD"

# ---------------- BRAPI ----------------
async def _fetch_brapi(symbol: str) -> Optional[Dict[str, Any]]:
    base_symbol = symbol.replace("^", "")
    params = {"range": "1d"}
    if BRAPI_TOKEN:
        params["token"] = BRAPI_TOKEN

    try:
        async with httpx.AsyncClient(timeout=BRAPI_TIMEOUT, headers=HTTP_HEADERS) as client:
            r = await client.get(BRAPI_URL.format(symbol=base_symbol), params=params)
            if r.status_code != 200:
                return None
            try:
                data = r.json()
            except json.JSONDecodeError:
                return None
            if not data or "results" not in data or not data["results"]:
                return None
            return data["results"][0]
    except Exception:
        return None

def _parse_brapi(symbol: str, data: Dict[str, Any]) -> QuoteInternal:
    last = data.get("regularMarketPrice") or data.get("close") or data.get("price")
    change_pct = data.get("regularMarketChangePercent") or data.get("changePercent")
    currency = data.get("currency") or _ccy(symbol)
    market_cap = data.get("marketCap")
    volume = data.get("regularMarketVolume") or data.get("volume")
    updated_at = data.get("regularMarketTime") or data.get("updatedAt") or _now_iso_utc()

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

# ---------------- Yahoo (leve) ----------------
def _yf_last_fast(t: yf.Ticker) -> Optional[float]:
    # evita .info; usa history leve
    try:
        df = t.history(period="1d", interval="1m", auto_adjust=False)
        if df is not None and not df.empty:
            return float(df["Close"].dropna().iloc[-1])
    except Exception:
        pass
    try:
        df = t.history(period="5d", interval="5m", auto_adjust=False)
        if df is not None and not df.empty:
            return float(df["Close"].dropna().iloc[-1])
    except Exception:
        pass
    # fallback p/ fechamento diário
    try:
        df = t.history(period="2d", interval="1d", auto_adjust=False)
        if df is not None and not df.empty:
            return float(df["Close"].dropna().iloc[-1])
    except Exception:
        pass
    return None

def _yf_daily_change_pct(t: yf.Ticker, last: Optional[float]) -> Optional[float]:
    try:
        df = t.history(period="2d", interval="1d", auto_adjust=False)
        if df is not None and len(df) >= 2 and "Close" in df.columns:
            prev = float(df["Close"].iloc[-2])
            curr = float(last if last is not None else df["Close"].iloc[-1])
            if prev > 0:
                return (curr / prev - 1.0) * 100.0
    except Exception:
        pass
    return None

def _fetch_yahoo_sync(symbol: str) -> Optional[Dict[str, Any]]:
    t = yf.Ticker(symbol)
    out: Dict[str, Any] = {}
    last = _yf_last_fast(t)
    if last is None:
        return None
    out["last"] = last
    out["currency"] = _ccy(symbol)
    # market cap e volume (não confiáveis via .info sob 429) ficam None se faltar
    out["market_cap"] = None
    out["volume"] = None
    out["change_pct"] = _yf_daily_change_pct(t, last)
    return out

def _parse_yahoo(symbol: str, data: Dict[str, Any]) -> QuoteInternal:
    currency = data.get("currency") or _ccy(symbol)
    last = data.get("last")
    market_cap = data.get("market_cap")
    volume = data.get("volume")
    change_pct = data.get("change_pct")
    notes: List[str] = []
    if change_pct is None:
        notes.append("Variação diária estimada indisponível")

    return QuoteInternal(
        price=QuoteOutPrice(
            last=float(last) if last is not None else None,
            change_pct=float(change_pct) if change_pct is not None else None,
            currency=currency,
            asof=_now_iso_utc(),
            source="yahoo"
        ),
        market_cap=QuoteOutMarketCap(
            value=float(market_cap) if market_cap is not None else None,
            currency=currency
        ),
        volume=QuoteOutVolume(value=float(volume) if volume is not None else None),
        status=QuoteOutStatus(confidence="medium", notes=notes)
    )

# ---------------- Stooq (fechamento) ----------------
def _stooq_symbol(symbol: str) -> str:
    s = symbol.lower()
    return s  # petr4.sa, aapl, etc.

def _fetch_stooq(symbol: str) -> Optional[Dict[str, Any]]:
    url = f"https://stooq.com/q/d/l/?s={_stooq_symbol(symbol)}&i=d"
    try:
        r = httpx.get(url, timeout=STOOQ_TIMEOUT, headers={"User-Agent": HTTP_HEADERS["User-Agent"]})
        if r.status_code != 200 or not r.text or r.text.strip().lower().startswith("no data"):
            return None
        buf = io.StringIO(r.text)
        reader = csv.DictReader(buf)
        rows = [row for row in reader if row.get("Close")]
        if not rows:
            return None
        last_row = rows[-1]
        close = float(last_row["Close"])
        vol = float(last_row["Volume"]) if last_row.get("Volume") else None
        return {
            "last": close,
            "volume": vol,
            "currency": _ccy(symbol),
            "asof": last_row.get("Date"),
        }
    except Exception:
        return None

def _parse_stooq(symbol: str, data: Dict[str, Any]) -> QuoteInternal:
    return QuoteInternal(
        price=QuoteOutPrice(
            last=float(data["last"]) if data.get("last") is not None else None,
            change_pct=None,
            currency=data.get("currency") or _ccy(symbol),
            asof=str(data.get("asof") or _now_iso_utc()),
            source="stooq"
        ),
        market_cap=QuoteOutMarketCap(value=None, currency=data.get("currency") or _ccy(symbol)),
        volume=QuoteOutVolume(value=float(data["volume"]) if data.get("volume") is not None else None),
        status=QuoteOutStatus(confidence="medium", notes=["Último fechamento (Stooq)"])
    )

# =========================
# Orquestrador com RACE
# =========================
class QuoteOrchestrator:
    """
    Concorre entre BRAPI (se token), Yahoo (leve) e Stooq, retorna a primeira válida.
    Priorização: brapi > yahoo > stooq. Cache 30s.
    """

    def __init__(self):
        self.cache = _CACHE

    async def _get_brapi(self, symbol: str) -> Optional[QuoteInternal]:
        if not BRAPI_TOKEN:
            return None
        raw = await _fetch_brapi(symbol)
        return _parse_brapi(symbol, raw) if raw else None

    async def _get_yahoo(self, symbol: str) -> Optional[QuoteInternal]:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _fetch_yahoo_sync, symbol)
        return _parse_yahoo(symbol, data) if data else None

    async def _get_stooq(self, symbol: str) -> Optional[QuoteInternal]:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _fetch_stooq, symbol)
        return _parse_stooq(symbol, data) if data else None

    async def get_quote(self, resolved: ResolvedSymbol, prefer: Optional[str] = None) -> QuoteInternal:
        cache_key = f"{resolved.symbol}:{prefer or 'auto'}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        tasks = []
        # ordem base
        providers = []
        if BRAPI_TOKEN:
            providers.append(("brapi", self._get_brapi(resolved.symbol)))
        providers.append(("yahoo", self._get_yahoo(resolved.symbol)))
        providers.append(("stooq", self._get_stooq(resolved.symbol)))

        # prefer move para frente
        if prefer:
            providers.sort(key=lambda x: 0 if x[0] == prefer else 1)

        # lança todas
        tasks_map = {name: asyncio.create_task(coro) for name, coro in providers}

        # coleta com prioridade: se vários resolvem, escolhe por ranking
        ranking = {"brapi": 0, "yahoo": 1, "stooq": 2}
        results: Dict[str, Optional[QuoteInternal]] = {k: None for k, _ in providers}

        for name, task in tasks_map.items():
            try:
                res = await asyncio.wait_for(task, timeout=YF_TIMEOUT if name == "yahoo" else BRAPI_TIMEOUT)
                results[name] = res
            except Exception:
                results[name] = None

        # escolhe o primeiro disponível pela prioridade
        best = None
        best_name = None
        for name in sorted(results.keys(), key=lambda n: ranking.get(n, 9)):
            if results[name] is not None:
                best = results[name]
                best_name = name
                break

        if best is None:
            # falhou tudo: constrói objeto mínimo com nota
            best = QuoteInternal(
                price=QuoteOutPrice(last=None, change_pct=None, currency=_ccy(resolved.symbol), asof=_now_iso_utc(), source="none"),
                market_cap=QuoteOutMarketCap(value=None, currency=_ccy(resolved.symbol)),
                volume=QuoteOutVolume(value=None),
                status=QuoteOutStatus(confidence="low", notes=["Nenhuma fonte disponível no momento"])
            )

        # validações finais
        self._validate(best)
        # cacheia
        self.cache[cache_key] = best
        return best

    def _validate(self, q: QuoteInternal) -> None:
        if q.price.last is not None and (math.isnan(q.price.last) or q.price.last <= 0):
            q.status.notes.append("Preço inválido ou ausente")
            q.status.confidence = "low"
        if not q.price.currency:
            q.price.currency = _ccy("X.SA")
            q.status.notes.append("Moeda inferida automaticamente")
