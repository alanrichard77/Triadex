import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from resolver import resolve_symbol
from providers import QuoteOrchestrator
from schemas import QuoteOut, HealthOut
from utils import to_iso_brt

# ===== Logging básico e estruturado =====
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | triadex | %(message)s"
)
log = logging.getLogger("triadex")

app = FastAPI(title="Triadex • Módulo 1", version="0.1.0")

# Static e templates
app.mount("/static", StaticFiles(directory="ui/static"), name="static")
templates = Jinja2Templates(directory="ui/templates")

# Orquestrador de cotações com fallback e cache interno
orchestrator = QuoteOrchestrator()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """
    UI minimalista, dark, com busca e um cartão de resultado.
    """
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health", response_model=HealthOut)
async def health():
    return HealthOut(
        status="ok",
        time_utc=datetime.now(timezone.utc).isoformat()
    )

@app.get("/api/quote", response_model=QuoteOut)
async def api_quote(q: str = Query(..., min_length=1, description="Ticker ou nome, ex: PETR4, VALE3, AAPL, IVVB11"),
                    prefer: Optional[str] = Query(None, description="Fonte preferida, ex: brapi ou yahoo")):
    """
    Resolve o ticker, consulta na Brapi com fallback no Yahoo Finance,
    valida moeda e horário, normaliza saída e devolve JSON padronizado.
    """
    symbol_in, resolved = resolve_symbol(q)
    log.info(f"resolve_symbol: in='{q}' -> resolved='{resolved.symbol}' exch='{resolved.exchange}'")

    try:
        quote = await orchestrator.get_quote(resolved, prefer=prefer)
    except Exception as e:
        log.exception("Erro ao obter cotação")
        raise HTTPException(status_code=502, detail=str(e))

    # Padroniza resposta
    payload = QuoteOut(
        ticker_in=symbol_in,
        resolved=resolved,
        price=quote.price,
        market_cap=quote.market_cap,
        volume=quote.volume,
        status=quote.status
    )
    return JSONResponse(json.loads(payload.model_dump_json()))

# Tratamento global de erros
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content={"detail": "Erro interno ao processar a requisição. Tente novamente em instantes."}
    )
