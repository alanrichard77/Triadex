from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
import logging
import json
from typing import Optional

from app.services.data_provider import get_quote
from app.services.fundamentals import get_fundamentals
from app.models.quote import QuoteResponse

app = FastAPI(title="Triadex Core", version="1.1")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("triadex")

def _now():
    return datetime.now(timezone.utc).isoformat()

@app.get("/")
def root():
    return {"Triadex": "Core Engine ativo", "status": "ok"}

@app.get("/health")
def health():
    return {"status": "ok", "time_utc": _now()}

# --------- QUOTES ----------
@app.get("/api/quote", response_model=QuoteResponse)
async def api_quote(ticker: str = Query(..., description="Ticker ex: PETR4, VALE3, AAPL")):
    try:
        data = await get_quote(ticker)
        return JSONResponse(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter dados: {str(e)}")

# --------- FUNDAMENTALS ----------
@app.get("/api/fundamentals")
async def api_fundamentals(ticker: str = Query(..., description="Ticker ex: PETR4, VALE3, AAPL")):
    data = await get_fundamentals(ticker)
    return JSONResponse(data)

# --------- SUMMARY (Quote + Fundamentals) ----------
@app.get("/api/summary")
async def api_summary(ticker: str = Query(..., description="Ticker ex: PETR4, VALE3, AAPL")):
    q = await get_quote(ticker)
    f = await get_fundamentals(ticker)
    return JSONResponse({"quote": q, "fundamentals": f})
