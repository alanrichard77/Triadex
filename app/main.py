from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from app.services.data_provider import get_quote
from app.models.quote import QuoteResponse
import logging

app = FastAPI(title="Triadex Core", version="1.0")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

@app.get("/api/quote", response_model=QuoteResponse)
async def api_quote(
    ticker: str = Query(..., description="Ticker ex: PETR4, VALE3, AAPL"),
):
    try:
        data = await get_quote(ticker)
        return JSONResponse(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter dados: {str(e)}")

@app.get("/")
def root():
    return {"Triadex": "Core Engine ativo", "status": "ok"}

