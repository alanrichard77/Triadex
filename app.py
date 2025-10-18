import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse, PlainTextResponse
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

BASE_DIR = os.path.abspath(os.getcwd())
TPL_DIR = os.path.join("ui", "templates")
STATIC_DIR = os.path.join("ui", "static")

log.info(f"BASE_DIR={BASE_DIR}")
log.info(f"TPL_DIR={TPL_DIR} exists={os.path.exists(TPL_DIR)}")
log.info(f"STATIC_DIR={STATIC_DIR} exists={os.path.exists(STATIC_DIR)}")

app = FastAPI(title="Triadex • Módulo 1", version="0.1.1")

# Static: check_dir=False evita crash se a pasta não existir no build
app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")
templates = Jinja2Templates(directory=TPL_DIR)

# Orquestrador de cotações (brapi -> yahoo)
orchestrator = QuoteOrchestrator()

FALLBACK_HOME = """<!doctype html>
<html lang="pt-br"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Triadex</title>
<style>body{background:#0b0f17;color:#e8eef9;font-family:system-ui,Arial;margin:0}
.container{max-width:720px;margin:40px auto;padding:16px}
.card{background:#121824;border:1px solid #1b2433;border-radius:14px;padding:16px}
h1{margin:0 0 6px 0}small{color:#9db0cf}
input,button{padding:12px;border-radius:10px;border:1px solid #1b2433}
input{background:#0f1624;color:#e8eef9;width:100%;margin-top:8px}
button{background:#4ea1ff;color:#001427;font-weight:600;margin-top:8px;border:0}
pre{white-space:pre-wrap;background:#0f1624;padding:12px;border-radius:10px}
</style></head><body>
<div class="container">
  <h1>Triadex</h1>
  <p class="card">A interface não encontrou <code>ui/templates/index.html</code>. O backend está OK. Você pode criar as pastas <code>ui/templates</code> e <code>ui/static</code> ou usar esta página de fallback.</p>
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
</body></html>"""

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """
    Tenta renderizar index.html; se não existir, devolve uma UI de fallback.
    """
    try:
        path = os.path.join(TPL_DIR, "index.html")
        if not os.path.exists(path):
            log.warning("index.html não encontrado, servindo FALLBACK_HOME")
            return HTMLResponse(FALLBACK_HOME)
        return temp
