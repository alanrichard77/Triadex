import os
import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from resolver import resolve_symbol
from providers import QuoteOrchestrator
from schemas import QuoteOut, HealthOut
from watchlists import WATCHLISTS

# ===== Logging estruturado =====
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | triadex | %(message)s"
)
log = logging.getLogger("triadex")

# Pastas de UI
TPL_DIR = os.path.join("ui", "templates")
STATIC_DIR = os.path.join("ui", "static")

app = FastAPI(title="Triadex • Módulo 1", version="0.2.0")

# Static com tolerância a ausência de diretório
app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")

# Templates Jinja (se a pasta não existir, a rota "/" usa fallback)
templates = Jinja2Templates(directory=TPL_DIR)

# Orquestrador de cotações com fallback
orchestrator = QuoteOrchestrator()

# HTML fallback (sem expor detalhes internos)
FALLBACK_HOME = '''<!doctype html>
<html lang="pt-br"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Triadex</title>
<style>body{background:#0b0f17;color:#e8eef9;font-family:system-ui,Arial;margin:0}
.container{max-width:720px;margin:40px auto;padding:16px}
.card{background:#121824;border:1px solid #1b2433;border-radius:14px;padding:16px}
h1{margin:0 0 6px 0}small{color:#9db0cf}
input,button,select{padding:12px;border-radius:10px;border:1px solid #1b2433}
input{background:#0f1624;color:#e8eef9;width:100%;margin-top:8px}
button{background:#4ea1ff;color:#001427;font-weight:600;margin-top:8px;border:0;cursor:pointer}
pre{white-space:pre-wrap;background:#0f1624;padding:12px;border-radius:10px}
.table{width:100%;border-collapse:collapse;margin-top:12px}
.table th,.table td{border-bottom:1px solid #1b2433;padding:8px;text-align:right}
.table th:first-child,.table td:first-child{text-align:left}
.badge{font-size:12px;color:#9db0cf}
.up{color:#3ad07a}.down{color:#ff5c5c}
</style></head><body>
<div class="container">
  <h1>Triadex</h1>
  <div class="card">
    <div><span class=badge>Primeira tela em modo mínimo</span></div>
    <label>Buscar ticker</label>
    <input id="q" placeholder="PETR4, VALE3, IVVB11, AAPL">
    <button onclick="go()">Buscar</button>
    <pre id="out"></pre>
    <div style="margin-top:12px">
      <label>Lista rápida</label>
      <select id="lst"></select>
      <button onclick="loadList()">Carregar</button>
      <table class="table" id="tbl"></table>
    </div>
  </div>
</div>
<script>
async function go(){
  const q=document.getElementById('q').value.trim(); if(!q) return;
  const r=await fetch('/api/quote?q='+encodeURIComponent(q));
  document.getElementById('out').textContent = await r.text();
}
async function loadLists(){
  const r=await fetch('/api/lists'); const data=await r.json();
  const sel=document.getElementById('lst'); sel.innerHTML='';
  data.forEach(x=>{ const o=document.createElement('option'); o.value=x.key; o.textContent=x.label; sel.appendChild(o); })
}
async function loadList(){
  const key=document.getElementById('lst').value;
  const r=await fetch('/api/watchlist?list='+encodeURIComponent(key));
  const data=await r.json();
  const tbl=document.getElementById('tbl');
  tbl.innerHTML='<tr><th>Ticker</th><th>Preço</th><th>Var%</th><th>Volume</th><th>Market Cap</th></tr>';
  data.items.forEach(row=>{
    const tr=document.createElement('tr');
    const pct=row.price.change_pct;
    const cls=(pct==null)?'':(pct>=0?'up':'down');
    tr.innerHTML = `<td>${row.resolved.symbol}</td>
                    <td style="text-align:right">${row.price.last??'—'} ${row.price.currency||''}</td>
                    <td style="text-align:right" class="${cls}">${pct==null?'—':(pct>0?'+':'')+pct.toFixed(2)+'%'}</td>
                    <td style="text-align:right">${row.volume.value??'—'}</td>
                    <td style="text-align:right">${row.market_cap.value??'—'} ${row.market_cap.currency||''}</td>`;
    tbl.appendChild(tr);
  });
}
loadLists();
</script>
</body></html>'''

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    index_path = os.path.join(TPL_DIR, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse(FALLBACK_HOME, status_code=200)
    try:
        return templates.TemplateResponse("index.html", {"request": request})
    except Exception:
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
    try:
        quote = await orchestrator.get_quote(resolved, prefer=prefer)
    except Exception as e:
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

# ======= NOVOS ENDPOINTS: listas e watchlist =======

@app.get("/api/lists")
async def api_lists():
    """Retorna o catálogo de listas disponíveis (id e label)."""
    out = [{"key": k, "label": v.get("label", k)} for k, v in WATCHLISTS.items()]
    return JSONResponse(out)

@app.get("/api/watchlist")
async def api_watchlist(
    list_key: str = Query(..., alias="list", description="Chave da watchlist, ex: br_bluechips"),
    prefer: Optional[str] = Query(None, description="Fonte preferida, ex: brapi ou yahoo"),
    limit: Optional[int] = Query(None, ge=1, le=100, description="Limite opcional de símbolos")
):
    wl = WATCHLISTS.get(list_key)
    if not wl:
        raise HTTPException(status_code=404, detail="Lista não encontrada")

    syms = wl.get("symbols", [])
    if limit:
        syms = syms[:limit]

    # Resolve símbolos (aplica heurística .SA se o usuário/arquivo não tiver)
    resolved_list = [resolve_symbol(s)[1] for s in syms]

    # Concorre 5 em 5 para evitar rate-limits
    sem = asyncio.Semaphore(5)
    async def fetch_one(resolved):
        async with sem:
            try:
                q = await orchestrator.get_quote(resolved, prefer=prefer)
                return {
                    "resolved": resolved.model_dump(),
                    "price": q.price.model_dump(),
                    "market_cap": q.market_cap.model_dump(),
                    "volume": q.volume.model_dump(),
                    "status": q.status.model_dump(),
                }
            except Exception as e:
                return {
                    "resolved": resolved.model_dump(),
                    "price": {"last": None, "change_pct": None, "currency": None, "asof": None, "source": "error"},
                    "market_cap": {"value": None, "currency": None},
                    "volume": {"value": None},
                    "status": {"confidence": "low", "notes": [f"erro: {str(e)[:120]}"]},
                }

    items = await asyncio.gather(*[fetch_one(r) for r in resolved_list])
    return JSONResponse({"list": {"key": list_key, "label": wl.get("label", list_key)}, "items": items})
