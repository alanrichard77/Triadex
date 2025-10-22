from fastapi import FastAPI, Query
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

# ---------- HOME HTML embutido (sem imports externos) ----------
HOME_HTML = """<!doctype html>
<html lang="pt-br"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Triadex</title>
<style>
:root{--bg:#0b0f17;--card:#121824;--text:#e8eef9;--muted:#9db0cf;--border:#1b2433;--brand:#4ea1ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,Segoe UI,Roboto,Arial}
.container{max-width:980px;margin:40px auto;padding:16px}
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px}
h1{margin:0 0 8px 0} .sub{color:var(--muted);margin:0 0 18px}
.row{display:flex;gap:10px;flex-wrap:wrap}
input,button{padding:12px 14px;border-radius:10px;border:1px solid var(--border);font-size:15px}
input{background:#0f1624;color:var(--text);flex:1;min-width:240px}
button{background:var(--brand);border:0;color:#001427;font-weight:700;cursor:pointer}
pre{white-space:pre-wrap;background:#0f1624;border:1px solid var(--border);border-radius:10px;padding:14px;overflow:auto}
a{color:var(--brand);text-decoration:none}
.footer{display:flex;justify-content:space-between;color:var(--muted);margin-top:8px;font-size:12px}
small.muted{color:var(--muted)}
</style></head>
<body>
<div class="container">
  <h1>Triadex</h1>
  <p class="sub">Core Engine ativo. Consulte um ticker e veja <b>cotação + fundamentals</b> em uma única chamada.</p>

  <div class="card">
    <div class="row">
      <input id="q" placeholder="Ex.: PETR4, VALE3, IVVB11, AAPL" value="PETR4"/>
      <button id="btn" onclick="go()">Buscar</button>
    </div>
    <p><small class="muted">Exemplos rápidos:
      <a href="#" onclick="demo('PETR4')">PETR4</a> ·
      <a href="#" onclick="demo('VALE3')">VALE3</a> ·
      <a href="#" onclick="demo('AAPL')">AAPL</a></small>
    </p>
    <pre id="out">{ "dica": "o retorno de /api/summary aparece aqui" }</pre>
  </div>

  <div class="footer">
    <span>Endpoints: <a href="/docs">/docs</a> · <a href="/api/quote?ticker=PETR4">/api/quote</a> · <a href="/api/fundamentals?ticker=PETR4">/api/fundamentals</a></span>
    <span>@triadex</span>
  </div>
</div>
<script>
let ctrl;
function demo(t){document.getElementById('q').value=t; go();}
function busy(b){const btn=document.getElementById('btn'); btn.disabled=b; btn.textContent=b?'Buscando...':'Buscar';}
async function go(){
  const q=document.getElementById('q').value.trim(); if(!q) return;
  if(ctrl) ctrl.abort(); ctrl = new AbortController(); busy(true);
  try{
    const r = await fetch('/api/summary?ticker='+encodeURIComponent(q), {signal:ctrl.signal});
    const js = await r.json();
    document.getElementById('out').textContent = JSON.stringify(js, null, 2);
  }catch(e){ document.getElementById('out').textContent = JSON.stringify({erro:String(e)}, null, 2); }
  finally{ busy(false); }
}
</script>
</body></html>"""

# ---------- Rotas ----------
@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(HOME_HTML)

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
