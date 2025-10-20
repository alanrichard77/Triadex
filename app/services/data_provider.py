import httpx, yfinance as yf, csv, io, asyncio, json
from datetime import datetime
from typing import Dict

# --- Configurações ---
BRAPI_URL = "https://brapi.dev/api/quote/{ticker}"
HEADERS = {"User-Agent": "Triadex/1.0"}
CACHE: Dict[str, Dict] = {}

async def get_quote(ticker: str) -> Dict:
    ticker = ticker.upper().strip()
    if not ticker.endswith(".SA") and len(ticker) == 5:
        ticker += ".SA"

    # --- Cache 60s ---
    if ticker in CACHE and (datetime.now().timestamp() - CACHE[ticker]["ts"] < 60):
        return CACHE[ticker]["data"]

    data = await _fetch_brapi(ticker) or _fetch_yahoo(ticker) or _fetch_stooq(ticker)

    if not data:
        raise ValueError("Nenhuma fonte disponível")

    CACHE[ticker] = {"ts": datetime.now().timestamp(), "data": data}
    return data

# --- BRAPI ---
async def _fetch_brapi(ticker: str):
    try:
        async with httpx.AsyncClient(timeout=3.0, headers=HEADERS) as client:
            r = await client.get(BRAPI_URL.format(ticker=ticker))
            if r.status_code != 200:
                return None
            js = r.json()
            if "results" not in js or not js["results"]:
                return None
            q = js["results"][0]
            return {
                "ticker": ticker,
                "name": q.get("longName"),
                "price": {"last": q.get("regularMarketPrice"), "change_pct": q.get("regularMarketChangePercent"), "currency": "BRL", "source": "brapi"},
                "market_cap": q.get("marketCap"),
                "volume": q.get("regularMarketVolume"),
                "updated_at": datetime.now().isoformat(),
                "confidence": "high",
                "notes": "Fonte principal BRAPI"
            }
    except Exception:
        return None

# --- Yahoo Fallback ---
def _fetch_yahoo(ticker: str):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="2d", interval="1d")
        if df.empty: return None
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) > 1 else last
        pct = (last / prev - 1) * 100 if prev > 0 else 0
        return {
            "ticker": ticker,
            "name": ticker,
            "price": {"last": last, "change_pct": pct, "currency": "BRL", "source": "yahoo"},
            "market_cap": None,
            "volume": None,
            "updated_at": datetime.now().isoformat(),
            "confidence": "medium",
            "notes": "Fallback Yahoo Finance"
        }
    except Exception:
        return None

# --- Stooq Fechamento ---
def _fetch_stooq(ticker: str):
    try:
        url = f"https://stooq.com/q/d/l/?s={ticker.lower()}&i=d"
        r = httpx.get(url, timeout=3.0)
        if r.status_code != 200 or not r.text: return None
        rows = list(csv.DictReader(io.StringIO(r.text)))
        if not rows: return None
        last = float(rows[-1]["Close"])
        return {
            "ticker": ticker,
            "name": ticker,
            "price": {"last": last, "change_pct": None, "currency": "BRL", "source": "stooq"},
            "market_cap": None,
            "volume": None,
            "updated_at": datetime.now().isoformat(),
            "confidence": "low",
            "notes": "Fechamento último pregão"
        }
    except Exception:
        return None

