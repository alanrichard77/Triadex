import os
import csv
import io
import math
import httpx
import yfinance as yf
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

# =========================
# Config
# =========================
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Triadex/1.0 Chrome/122 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"}
TIMEOUT = 4.0

BRAPI_TOKEN = os.getenv("BRAPI_TOKEN", "").strip()  # opcional
BRAPI_URL = "https://brapi.dev/api/quote/{ticker}{query}"  # query = ?range=1d&token=...

# Cache simples (TTL curto implementado por timestamp)
_CACHE: Dict[str, Dict] = {}

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _is_b3_code(raw: str) -> bool:
    s = raw.upper().strip()
    # B3 mais comum: 4 letras + 1 dígito, ou 5 letras (fundos) – manter simples e eficaz
    return (len(s) in (5,6)) and s[-1].isdigit() or s.endswith("11") or s.endswith(".SA")

def _resolve_symbol(raw: str) -> str:
    s = raw.upper().strip()
    if s.endswith(".SA"):
        return s
    if _is_b3_code(s):
        return f"{s}.SA"
    return s  # US e outros

def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))

def _build_payload(
    symbol: str, name: Optional[str], last: Optional[float], change_pct: Optional[float],
    currency: Optional[str], source: str, confidence: str, market_cap=None, volume=None, notes: Optional[str]=None
) -> Dict:
    return {
        "ticker": symbol,
        "name": name,
        "price": {
            "last": last,
            "change_pct": change_pct,
            "currency": currency,
            "source": source,
        },
        "market_cap": market_cap,
        "volume": volume,
        "updated_at": _now_iso(),
        "confidence": confidence,
        "notes": notes,
    }

# =========================
# Providers
# =========================

async def _fetch_brapi(symbol: str) -> Optional[Dict]:
    if not BRAPI_TOKEN:
        return None
    q = f"?range=1d&token={BRAPI_TOKEN}"
    url = BRAPI_URL.format(ticker=symbol, query=q)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS) as client:
            r = await client.get(url)
        if r.status_code != 200:
            return None
        js = r.json()
        if not js or "results" not in js or not js["results"]:
            return None
        q0 = js["results"][0]
        return _build_payload(
            symbol=symbol,
            name=q0.get("longName") or q0.get("shortName"),
            last=q0.get("regularMarketPrice") or q0.get("close"),
            change_pct=q0.get("regularMarketChangePercent"),
            currency=q0.get("currency") or "BRL",
            source="brapi",
            confidence="high",
            market_cap=q0.get("marketCap"),
            volume=q0.get("regularMarketVolume"),
            notes="Fonte BRAPI"
        )
    except Exception:
        return None

def _fetch_yahoo(symbol: str) -> Optional[Dict]:
    try:
        t = yf.Ticker(symbol)

        # 1) fast_info (mais rápido)
        fi = getattr(t, "fast_info", None)
        name = None
        last = None
        prev = None
        currency = None
        if fi:
            last = fi.get("last_price") or fi.get("lastPrice")
            prev = fi.get("previousClose")
            currency = fi.get("currency")
        # 2) info (mais completo; pode rate-limit)
        info = {}
        try:
            info = t.info or {}
            if not name:
                name = info.get("longName") or info.get("shortName")
            if not currency:
                currency = info.get("currency")
            if not _ok(prev):
                prev = info.get("previousClose")
            if not _ok(last):
                last = info.get("regularMarketPrice") or info.get("currentPrice")
        except Exception:
            pass

        # 3) history/download (fechamento)
        if not _ok(last):
            df = t.history(period="5d", interval="1d", auto_adjust=False, prepost=False)
            if df is not None and not df.empty:
                last = float(df["Close"].iloc[-1])
                if len(df) > 1:
                    prev = float(df["Close"].iloc[-2])

        change_pct = None
        if _ok(last) and _ok(prev) and prev:
            change_pct = (float(last) / float(prev) - 1.0) * 100.0

        if _ok(last):
            return _build_payload(
                symbol=symbol,
                name=name or symbol,
                last=float(last),
                change_pct=float(change_pct) if _ok(change_pct) else None,
                currency=currency or ("BRL" if symbol.endswith(".SA") else "USD"),
                source="yahoo",
                confidence="medium",
                market_cap=info.get("marketCap"),
                volume=info.get("regularMarketVolume"),
                notes="Yahoo Finance"
            )
        return None
    except Exception:
        return None

def _fetch_stooq(symbol: str) -> Optional[Dict]:
    # Stooq: apenas fechamento diário (CSV)
    try:
        url = f"https://stooq.com/q/d/l/?s={symbol.lower()}&i=d"
        r = httpx.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200 or not r.text:
            return None
        rows = list(csv.DictReader(io.StringIO(r.text)))
        if not rows:
            return None
        last = float(rows[-1]["Close"])
        prev = float(rows[-2]["Close"]) if len(rows) > 1 else None
        change_pct = (last / prev - 1) * 100.0 if prev else None
        return _build_payload(
            symbol=symbol,
            name=symbol,
            last=last,
            change_pct=change_pct,
            currency="BRL" if symbol.endswith(".SA") else "USD",
            source="stooq",
            confidence="low",
            market_cap=None,
            volume=None,
            notes="Fechamento do último pregão (Stooq)"
        )
    except Exception:
        return None

# =========================
# Facade
# =========================

async def get_quote(raw_ticker: str) -> Dict:
    """
    Estratégia:
    1) Resolve símbolo (.SA p/ B3)
    2) Tenta Yahoo (robusto para US e B3)
    3) Se BRAPI tiver token -> tenta
    4) Stooq como último recurso (fechamento)
    5) Se tudo falhar -> payload 'unavailable' (confidence=none)
    """
    symbol = _resolve_symbol(raw_ticker)

    # Cache 60s
    c = _CACHE.get(symbol)
    if c and (datetime.now(timezone.utc).timestamp() - c["ts"] < 60):
        return c["data"]

    # 1) Yahoo primeiro (melhor disponibilidade geral)
    y = _fetch_yahoo(symbol)
    if y:
        _CACHE[symbol] = {"ts": datetime.now(timezone.utc).timestamp(), "data": y}
        return y

    # 2) BRAPI (apenas se token)
    b = await _fetch_brapi(symbol)
    if b:
        _CACHE[symbol] = {"ts": datetime.now(timezone.utc).timestamp(), "data": b}
        return b

    # 3) Stooq
    s = _fetch_stooq(symbol)
    if s:
        _CACHE[symbol] = {"ts": datetime.now(timezone.utc).timestamp(), "data": s}
        return s

    # 4) Nada disponível -> nunca estoura erro para o cliente
    data = _build_payload(
        symbol=symbol, name=None, last=None, change_pct=None,
        currency="BRL" if symbol.endswith(".SA") else "USD",
        source="unavailable", confidence="none",
        notes="Todas as fontes de preço indisponíveis no momento"
    )
    _CACHE[symbol] = {"ts": datetime.now(timezone.utc).timestamp(), "data": data}
    return data
