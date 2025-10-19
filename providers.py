import os
import math
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List

import httpx
import yfinance as yf
from cachetools import TTLCache

from schemas import (
    ResolvedSymbol, QuoteOutPrice, QuoteOutMarketCap,
    QuoteOutStatus, QuoteOutVolume, QuoteInternal
)

# =========================
# Configuração & Cache
# =========================
_CACHE = TTLCache(maxsize=2048, ttl=int(os.getenv("CACHE_TTL", "30")))  # 30s intraday

BRAPI_URL = "https://brapi.dev/api/quote/{symbol}"
BRAPI_TIMEOUT = float(os.getenv("BRAPI_TIMEOUT", "2.5"))
YF_TIMEOUT = float(os.getenv("YF_TIMEOUT", "3.0"))

HTTP_HEADERS = {
    # Alguns endpoints bloqueiam user agents "desconhecidos". Usamos um UA neutro.
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Triadex/1.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _brl_if_b3(symbol: str) -> str:
    return "BRL" if symbol.upper().endswith(".SA") else "USD"


# =========================
# BRAPI (assíncrono)
# =========================
async def fetch_brapi(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Busca dados de cotação na BRAPI com 2 tentativas e tolerância a JSON inválido.
    Retorna dict normalizado da própria brapi (results[0]) ou None.
    """
    url = BRAPI_URL.format(symbol=symbol.replace("^", ""))
    params = {"range": "1d"}

    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=BRAPI_TIMEOUT, headers=HTTP_HEADERS) as client:
                r = await client.get(url, params=params)
                if r.status_code != 200:
                    continue
                # Tenta JSON; se vier HTML/HTML de bloqueio, isto irá falhar
                try:
                    data = r.json()
                except json.JSONDecodeError:
                    continue
                if not data or "results" not in data or not data["results"]:
                    continue
                return data["results"][0]
        except Exception:
            # timeout ou falha – tenta novamente
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
# YAHOO FINANCE (síncrono)
# =========================
def _yf_fast_info(t: yf.Ticker) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        fast = t.fast_info
        info["last"] = getattr(fast, "last_price", None)
        info["currency"] = getattr(fast, "currency", None)
        info["market_cap"] = getattr(fast, "market_cap", None)
        info["volume"] = getattr(fast, "last_volume", None)
    except Exception:
        return {}
    return info


def _yf_history_last_price(t: yf.Ticker) -> Optional[float]:
    """
    Busca último preço por histórico intraday. Tenta 1d/1m, 5d/5m.
    """
    try:
        df = t.history(period="1d", interval="1m", auto_adjust=False)
        if df is not None and not df.empty and "Close" in df.columns:
            return float(df["Close"].iloc[-1])
    except Exception:
        pass
    try:
        df = t.history(period="5d", interval="5m", auto_adjust=False)
        if df is not None and not df.empty and "Close" in df.columns:
            return float(df["Close"].dropna().iloc[-1])
    except Exception:
        pass
    return None


def _yf_daily_change_pct(t: yf.Ticker, last: Optional[float]) -> Optional[float]:
    """
    Calcula variação diária (%) usando os dois últimos fechamentos diários,
    ou last vs previousClose quando possível.
    """
    # Tenta previous close via info
    try:
        i = t.info
        prev = i.get("previousClose")
        if last is not None and prev:
            if prev > 0:
                return (last / float(prev) - 1.0) * 100.0
    except Exception:
        pass

    # Tenta pelos dois últimos candles diários
    try:
        df = t.history(period="2d", interval="1d", auto_adjust=False)
        if df is not None and len(df) >= 2 and "Close" in df.columns:
            prev = float(df["Close"].iloc[-2])
            curr = float(df["Close"].iloc[-1]) if last is None else float(last)
            if prev > 0:
                return (curr / prev - 1.0) * 100.0
    except Exception:
        pass
    return None


def fetch_yahoo_sync(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Estratégia Yahoo resiliente:
    1) fast_info
    2) history intraday
    3) info/history diário
    Retorna dict padronizado com chaves: last, currency, market_cap, volume, change_pct
    """
    t = yf.Ticker(symbol)
    out: Dict[str, Any] = {}

    # 1) fast_info
    fast = _yf_fast_info(t)
    out.update(fast)

    # Se last ausente, 2) tenta intraday
    if out.get("last") is None:
        last_hist = _yf_history_last_price(t)
        if last_hist is not None:
            out["last"] = last_hist

    # 3) market_cap/volume/currency via info
    try:
        i = t.info
        out.setdefault("currency", i.get("currency"))
        out.setdefault("market_cap", i.get("marketCap"))
        out.setdefault("volume", i.get("volume"))
    except Exception:
        # tudo bem
        pass

    # Calcular change_pct se possível
    out["change_pct"] = _yf_daily_change_pct(t, out.get("last"))

    # Nada encontrado? retorna None
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
        notes.append("Variação diária não disponível no Yahoo")

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
# ORQUESTRADOR COM FALLBACK
# =========================
class QuoteOrchestrator:
    """
    Orquestra consultas e aplica fallback automático entre BRAPI e Yahoo.
    Possui cache volátil (TTL 30s por padrão).
    """

    def __init__(self):
        self.cache = _CACHE

    async def get_quote(self, resolved: ResolvedSymbol, prefer: Optional[str] = None) -> QuoteInternal:
        cache_key = f"{resolved.symbol}:{prefer or 'auto'}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        providers = ["brapi", "yahoo"]
        if prefer in providers:
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
                        self._validate(parsed)
                        self.cache[cache_key] = parsed
                        return parsed

                elif p == "yahoo":
                    data = fetch_yahoo_sync(resolved.symbol)
                    if data:
                        parsed = parse_yahoo(resolved.symbol, data)
                        self._validate(parsed)
                        self.cache[cache_key] = parsed
                        return parsed

            except Exception as e:
                last_error = e
                continue

        # Se nada deu certo:
        raise RuntimeError(f"Todas as fontes falharam para {resolved.symbol}. {last_error or ''}")

    def _validate(self, q: QuoteInternal) -> None:
        # Preço inválido
        if q.price.last is not None and (math.isnan(q.price.last) or q.price.last <= 0):
            q.status.notes.append("Preço inválido ou ausente")
            q.status.confidence = "low"
        # Moeda ausente
        if not q.price.currency:
            q.price.currency = "BRL"
            q.status.notes.append("Moeda inferida automaticamente")
