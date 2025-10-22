from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse
from datetime import datetime, timezone
import logging

from app.services.data_provider import get_quote
from app.services.fundamentals import get_fundamentals
from app.models.quote import QuoteResponse

app = FastAPI(title="Triadex Core", version="1.2")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("triadex")

def _now():
    return datetime.now(timezone.utc).isoformat()

# (HOME_HTML mantido igual ao que você já tem)

# ... MANTENHA O HOME_HTML ATUAL (não repito aqui para encurtar) ...

@app.get("/", response_class=HTMLResponse)
def home():
    # use seu HOME_HTML atual — ou a versão que enviei antes
    from app.main_home import HOME_HTML as _HTML  # se preferir separar
    return HTMLResponse(_HTML)

@app.get("/health")
def health():
    return {"status": "ok", "time_utc": _now()}

@app.get("/api/quote", response_model=QuoteResponse)
async def api_quote(ticker: str = Query(..., description="Ticker ex: PETR4, VALE3, AAPL")):
    data = await get_quote(ticker)
    return JSONResponse(data)

@app.get("/api/fundamentals")
async def api_fundamentals(ticker: str = Query(..., description="Ticker ex: PETR4, VALE3, AAPL")):
    data = await get_fundamentals(ticker)
    return JSONResponse(data)

@app.get("/api/summary")
async def api_summary(ticker: str = Query(..., description="Ticker ex: PETR4, VALE3, AAPL")):
    q = await get_quote(ticker)
    try:
        f = await get_fundamentals(ticker)
    except Exception:
        f = {"ticker": ticker.upper(), "source": "none", "confidence": "low", "updated_at": _now()}
    return JSONResponse({"quote": q, "fundamentals": f})
