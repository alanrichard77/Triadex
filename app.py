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

app = FastAPI(title="Triadex • Módulo 1", version="0.1.2")

# Static com tolerância a ausência de diretório
app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")

# Templates Jinja, ok mesmo se a pasta não existir, pois tratamos na rota
templates = Jinja2Templates(directory=TPL_DIR)

# Orquestrador de cotações com fallback
orchestrator = QuoteOrchestrator()

# HTML fallback para quando ui/templates/index.html não existir
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
button{background:#4ea1ff;color:#001427;font-weight:600;margin-top:8px;border:0;cursor:pointer}
pre{white-space:pre-wrap;background:#0f1624;padding:12px;border-radius:10px}
</style></head><body>
<div class="cont
