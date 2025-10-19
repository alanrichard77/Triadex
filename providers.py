import os
import math
import csv
import io
import json
import time
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
_CACHE = TTLCache(maxsize=2048, ttl=int(os.getenv("CACHE_TTL", "30")))  # 30s

BRAPI_URL = "https://brapi.dev/api/quote/{symbol}"
BRAPI_TIMEOUT = float(os.getenv("BRAPI_TIMEOUT", "2.5"))
YF_TIMEOUT = float(os.getenv("YF_TIMEOUT", "3.0"))
BRAPI_TOKEN = os.getenv("BRAPI_TOKEN", "").strip()  # <- defina no Render (Environment)

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Triadex/1.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _brl_if_b3(symbol: str) -> str:
    return "BRL" if symbol.upper().endswith(".SA") else "USD"

def _is_b3(symbol: str) -> bool:
    return symbol.upper().endswith(".SA")

# =========================
# BRAPI (assíncrono)
# =========================
async def fetch_brapi(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Consulta BRAPI com 2 tentativas. Se BRAPI_TOKEN existir, envia no querystring.
    Retorna results[0] ou None.
    """
    base_symbol = symbol.replace("^", "")
    params = {"range": "1d"}
    if BRAPI_TOKEN:
        params["token"] = BRAPI_TOKEN

    for _ in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=BRAPI_TIMEOUT, headers=HTTP_HEADERS) as client:
                r = await client.get(BRAPI_URL.format(symbol=base_symbol), params=params)
                if r.status_code != 200:
                    continue
                try:
                    data = r.json()
                except json.JSONDecodeError:
                    continue
                if not data or "results" not in data or not data["results"]:
                    continue
                return data["results"][0]
        except Exception:
            continue
    return None


def parse_brapi(symbol: str, data: Dict[str, Any]) -> QuoteInternal:
    last = data.get("regularMarketPrice") or data.get("close") or data.get("price")
    change_pct = data.get("regularMarketChangePercent") or data.get("changePercent")
    currency = data.get("currency") or _brl_if_b3(symbol)
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

# =========================
# Yahoo Finance (síncrono)
# =========================
def _yf_try_fast_info(t: yf.Ticker) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        fast = t.fast_info
        out["last"] = getattr(fast, "last_price", None)
        out["currency"] = getattr(fast, "currency", None)
        out["market_cap"] = getattr(fast, "market_cap", None)
        out["volume"] = getattr(fast, "last_volume", None)
    except Exception:
        return {}
    return out

def _yf_hist_last(t: yf.Ticker, period: str, interval: str) -> Optional[float]:
    try:
        df = t.history(period=period, interval=interval, auto_adjust=False)
        if df is not None and not df.empty and "Close" in df.columns:
            return float(df["Close"].dropna().iloc[-1])
    except Exception:
        pass
    return None

def _yf_daily_change_pct(t: yf.Ticker, last: Optional[float]) -> Optional[float]:
    # via info.previousClose
    try:
        i = t.info
        prev = i.get("previousClose")
        if last is not None and prev and prev > 0:
            return (float(last) / float(prev) - 1.0) * 100.0
    except Exception:
        pass
    # via 2 últimos candles diários
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

def fetch_yahoo_sync(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Estratégia resiliente com pequenos backoffs para contornar 429.
    1) fast_info
    2) history 1d/1m e 5d/5m (preço intraday)
    3) info + history 2d (usa fechamento do último pregão)
    """
    t = yf.Ticker(symbol)
    out: Dict[str, Any] = {}

    # 1) fast_info com 2 tentativas
    for wait in (0.0, 0.5):
        if wait:
            time.sleep(wait)
        fi = _yf_try_fast_info(t)
        if fi:
            out.update(fi)
            break

    # 2) intraday (se last ausente)
    if out.get("last") is None:
        for (p, i), wait in ((("1d", "1m"), 0.0), (("5d", "5m"), 0.4)):
            if wait:
                time.sleep(wait)
            last = _yf_hist_last(t, p, i)
            if last is not None:
                out["last"] = last
                break

    # 3) info/diário para market_cap/volume/currency e change_pct
    try:
        i = t.info
        out.setdefault("currency", i.get("currency"))
        out.setdefault("market_cap", i.get("marketCap"))
        out.setdefault("volume", i.get("volume"))
    except Exception:
        pass

    out["change_pct"] = _yf_daily_change_pct(t, out.get("last"))

    # Se nada de relevante foi obtido, sinaliza falha
    if out.get("last") is None and out.get("market_cap") is None and out.get("volume") is None:
        return None

    return out

def parse_yahoo(symbol: str, data: Dict[str, Any]) -> QuoteInternal:
    currency = data.get("currency") or _brl_if_b3(symbol)
    last = data.get("last")
    market_cap = data.get("market_cap")
    volume = data.get("volume")
    change_pct = data.get("change_pct")

    notes: List[str] = []
    if change_pct is None:
        notes.append("Exibindo último preço/fechamento (var. diária indisponível)")

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
        status=QuoteOutStatus(confidence="medium" if notes else "high", notes=notes)
    )

# =========================
# Stooq (CSV público) - Fallback 3
# =========================
def _stooq_symbol(symbol: str) -> Optional[str]:
    s = symbol.lower()
    # Stooq usa .sa para B3 e sem sufixo p/ EUA
    if s.endswith(".sa") or s.endswith(".us"):
        return s
    if _is_b3(symbol):
        return s
    return s  # tenta como veio (AAPL -> aapl)

def fetch_stooq(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Retorna fechamento diário e volume do último pregão.
    Ex.: https://stooq.com/q/d/l/?s=petr4.sa&i=d
    CSV: Date,Open,High,Low,Close,Volume
    """
    ss = _stooq_symbol(symbol)
    if not ss:
        return None
    url = f"https://stooq.com/q/d/l/?s={ss}&i=d"
    try:
        r = httpx.get(url, timeout=2.5, headers={"User-Agent": HTTP_HEADERS["User-Agent"]})
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
            "currency": _brl_if_b3(symbol),
            "asof": last_row.get("Date"),
        }
    except Exception:
        return None

def parse_stooq(symbol: str, data: Dict[str, Any]) -> QuoteInternal:
    return QuoteInternal(
        price=QuoteOutPrice(
            last=float(data["last"]) if data.get("last") is not None else None,
            change_pct=None,  # não dá para calcular sem previousClose confiável
            currency=data.get("currency") or _brl_if_b3(symbol),
            asof=str(data.get("asof") or _now_iso_utc()),
            source="stooq"
        ),
        market_cap=QuoteOutMarketCap(value=None, currency=data.get("currency") or _brl_if_b3(symbol)),
        volume=QuoteOutVolume(value=float(data["volume"]) if data.get("volume") is not None else None),
        status=QuoteOutStatus(confidence="medium", notes=["Último fechamento obtido via Stooq"])
    )

# =========================
# Orquestrador
# =========================
class QuoteOrchestrator:
    """
    Fluxo: BRAPI (se token) → Yahoo → Stooq.
    Sempre que intraday indisponível, usamos fechamento do último pregão.
    """

    def __init__(self):
        self.cache = _CACHE

    async def get_quote(self, resolved: ResolvedSymbol, prefer: Optional[str] = None) -> QuoteInternal:
        cache_key = f"{resolved.symbol}:{prefer or 'auto'}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        providers = []
        # Se tem token, BRAPI primeiro; senão começa no Yahoo
        if BRAPI_TOKEN:
            providers = ["brapi", "yahoo", "stooq"]
        else:
            providers = ["yahoo", "stooq"]

        if prefer in providers:
            providers.remove(prefer)
            providers = [prefer] + providers

        last_error = None

        for p in providers:
            try:
                if p == "brapi":
                    raw = await fetch_brapi(resolved.symbol)
                    if raw:
                        parsed = parse_brapi(resolved.symbol, raw)
                        self._validate(parsed)
                        self.cache[cache_key] = parsed
                        return parsed

                if p == "yahoo":
                    raw = fetch_yahoo_sync(resolved.symbol)
                    if raw:
                        parsed = parse_yahoo(resolved.symbol, raw)
                        self._validate(parsed)
                        self.cache[cache_key] = parsed
                        return parsed

                if p == "stooq":
                    raw = fetch_stooq(resolved.symbol)
                    if raw:
                        parsed = parse_stooq(resolved.symbol, raw)
                        self._validate(parsed)
                        self.cache[cache_key] = parsed
                        return parsed

            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(f"Todas as fontes falharam para {resolved.symbol}. {last_error or ''}")

    def _validate(self, q: QuoteInternal) -> None:
        if q.price.last is not None and (math.isnan(q.price.last) or q.price.last <= 0):
            q.status.notes.append("Preço inválido ou ausente")
            q.status.confidence = "low"
        if not q.price.currency:
            q.price.currency = _brl_if_b3("X.SA")
            q.status.notes.append("Moeda inferida automaticamente")
