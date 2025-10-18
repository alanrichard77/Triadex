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

# ===== Logging estruturado =====
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | triadex | %(message)s"
)
log = logging.getLogger("triadex")

# Pastas de UI
TPL_DIR = os.path.join("ui", "templates")
STATIC_DIR = os.path.join("ui", "static")

app = FastAPI(title="Triadex • Módulo 1", version="0.1.3")

# Static com tolerância a ausência de diretório
app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")

# Templates Jinja (se a pasta não existir, a rota "/" usa fallback)
templates = Jinja2Templates(directory=TPL_DIR)

# Orquestrador de cotações com fallback
orchestrator = QuoteOrchestrator()

# HTML fallback sem usar aspas triplas duplas
FALLBACK_HOME = '''<!doctype html>
<html lang="pt-br"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Triadex</title>
<style>body{background:#0b0f17;color:#e8eef9;font-family:system-ui,Arial;margin:0}
.container{max-width:720px;margin:40px auto;padding:16px}
.card{background:#121824;border:1px solid #1b2433;border-radius:14px;padding:16px}
h1{margin:0 0 6px 0}small{color:#9db0cf}
input,button{padding:12px;border-radius:10px;border:1px solid #1b2433}
input{background:#0f1624;color:#e8eef9;width:100%;margin-top:8px}
button{background:#4ea1ff;color:#001427;font-weight:600;margin-top:8px;border:0;cursor:pointer}
pre{white-space:pre-wrap;background:#0f1624;padding:12px;border-radius:10px}
</style></head><body>
<div class="container">
  <h1>Triadex</h1>
  <div class="card">
    A interface não encontrou <code>ui/templates/index.html</code>. O backend está ok.
    Você pode criar as pastas <code>ui/templates</code> e <code>ui/static</code>, depois publicar novamente.
  </div>
  <div class="card"><label>Buscar ticker</label>
    <input id="q" placeholder="PETR4, VALE3, IVVB11, AAPL">
    <button onclick="go()">Buscar</button>
    <pre id="out"></pre>
  </div>
</div>
<script>
async function go(){
  const q=document.getElementById('q').value.trim();
  if(!q) return;
  const r=await fetch('/api/quote?q='+encodeURIComponent(q));
  document.getElementById('out').textContent = await r.text();
}
</script>
</body></html>'''

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """
    Tenta renderizar index.html, se não existir devolve a UI de fallback.
    """
    index_path = os.path.join(TPL_DIR, "index.html")
    if not os.path.exists(index_path):
        log.warning("index.html não encontrado, servindo FALLBACK_HOME")
        return HTMLResponse(FALLBACK_HOME, status_code=200)

    try:
        return templates.TemplateResponse("index.html", {"request": request})
    except Exception:
        log.exception("Erro ao renderizar index.html, servindo FALLBACK_HOME")
        return HTMLResponse(FALLBACK_HOME, status_code=200)

@app.get("/health", response_model=HealthOut)
async def health():
    return HealthOut(status="ok", time_utc=datetime.now(timezone.utc).isoformat())

@app.get("/api/quote", response_model=QuoteOut)
async def api_quote(
    q: str = Query(..., min_length=1, description="Ticker ou nome, ex: PETR4, VALE3, AAPL, IVVB11"),
    prefer: Optional[str] = Query(None, description="Fonte preferida, ex: brapi ou yahoo")
):
    symbol_in, resolved = resolve_symbol(q)
    log.info(f"resolve_symbol in='{q}' -> symbol='{resolved.symbol}' exch='{resolved.exchange}'")
    try:
        quote = await orchestrator.get_quote(resolved, prefer=prefer)
    except Exception as e:
        log.exception("Erro ao obter cotação")
        raise HTTPException(status_code=502, detail=str(e))

    payload = QuoteOut(
        ticker_in=symbol_in,
        resolved=resolved,
        price=quote.price,
        market_cap=quote.market_cap,
        volume=quote.volume,
        status=quote.status
    )
    return JSONResponse(json.loads(payload.model_dump_json()))

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content={"detail": "Erro interno ao processar a requisição. Tente novamente em instantes."}
    )
