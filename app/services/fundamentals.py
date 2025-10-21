import re
import math
import json
import httpx
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

from app.models.fundamentals import FundamentalsResponse, Ratio

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Triadex/1.0 Chrome/122 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"}
T_OUT = 4.0

# -------------------------
# Utilidades
# -------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _to_float(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    s = str(text).strip()
    if s == "" or s == "-" or s.lower() == "n/a":
        return None
    s = s.replace(".", "").replace("%", "").replace("R$", "").replace("$", "").replace("€", "")
    s = s.replace(",", ".")
    # sufixos k/m/b/trilhos
    m = re.match(r"([-+]?\d+(\.\d+)?)(\s*[kKmMbBtT])?$", s)
    if m:
        v = float(m.group(1))
        suf = (m.group(3) or "").lower().strip()
        if suf == "k": v *= 1e3
        elif suf == "m": v *= 1e6
        elif suf == "b": v *= 1e9
        elif suf == "t": v *= 1e12
        return v
    # fallback simples
    try:
        return float(s)
    except Exception:
        return None

def _ratio(v: Optional[float], unit: Optional[str] = None) -> Optional[Ratio]:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return Ratio(value=float(v), unit=unit)

def _pct(v: Optional[float]) -> Optional[Ratio]:
    return _ratio(v, "%") if v is not None else None

def _mul(v: Optional[float]) -> Optional[Ratio]:
    return _ratio(v, "x") if v is not None else None

# -------------------------
# StatusInvest (B3) — scraping tolerante a alterações
# -------------------------
async def _fetch_statusinvest(ticker: str) -> Optional[FundamentalsResponse]:
    # ticker sem .SA
    tk = ticker.replace(".SA", "").upper()
    urls = [
        f"https://statusinvest.com.br/acoes/{tk}",
        f"https://statusinvest.com.br/acao/{tk}",  # variantes antigas
    ]
    async with httpx.AsyncClient(timeout=T_OUT, headers=HEADERS, follow_redirects=True) as client:
        for url in urls:
            try:
                r = await client.get(url)
                if r.status_code != 200 or not r.text:
                    continue
                html = r.text
                soup = BeautifulSoup(html, "lxml")

                # Dados aparecem em diversos data-* attributes; tentamos extrair blocos JSON embutidos
                raw: Dict = {"url": url}

                # 1) Bloco de indicadores em data-* (cards)
                # Muitas páginas possuem scripts com "indicator-name" e "indicator-value".
                # Captura genérica:
                metrics: Dict[str, float] = {}

                for tag in soup.find_all(attrs={"data-indicator": True}):
                    try:
                        name = (tag.get("data-indicator") or "").strip().lower()
                        val = _to_float(tag.get("data-value"))
                        if name and val is not None:
                            metrics[name] = val
                    except Exception:
                        continue

                # 2) Alguns valores aparecem como <span class="...">12,34%</span> com label próximo
                # Vamos mapear por rótulos conhecidos:
                def grab_by_label(label_regex: str) -> Optional[float]:
                    lab = soup.find(string=re.compile(label_regex, re.I))
                    if not lab:
                        return None
                    # pega próximo número visível
                    nxt = lab.find_parent()
                    if not nxt:
                        return None
                    txt = re.findall(r"[-+]?\d[\d\.,]*%?", nxt.get_text(" ", strip=True))
                    if not txt:
                        return None
                    return _to_float(txt[-1])

                # montar resposta
                pe = metrics.get("p/l") or grab_by_label(r"P\/?L")
                pb = metrics.get("p/vpa") or grab_by_label(r"P\/?VPA|P\/?VPA")
                ev_ebitda = metrics.get("ev\/ebitda") or grab_by_label(r"EV\/?EBITDA")
                ps = metrics.get("p\/?sr") or grab_by_label(r"P\/?S")
                roe = metrics.get("roe") or grab_by_label(r"ROE")
                roic = metrics.get("roic") or grab_by_label(r"ROIC")
                net_margin = metrics.get("margem líquida") or grab_by_label(r"Margem.*L[ií]quida")
                ebit_margin = metrics.get("margem ebit") or grab_by_label(r"Margem.*EBIT")
                gross_margin = metrics.get("margem bruta") or grab_by_label(r"Margem.*Bruta")
                dy = metrics.get("dy") or grab_by_label(r"Dividend.? Yield|DY")
                payout = metrics.get("payout") or grab_by_label(r"Payout")
                nde = metrics.get("d[ií]vida l[ií]quida\/ebitda") or grab_by_label(r"D[ií]vida.*EBITDA")
                de = metrics.get("dívida\/patrim[oô]nio") or grab_by_label(r"D[ií]vida.*Patrim")

                resp = FundamentalsResponse(
                    ticker=ticker,
                    source="statusinvest",
                    confidence="high",
                    updated_at=_now(),
                    pe=_mul(pe),
                    pb=_mul(pb),
                    ev_ebitda=_mul(ev_ebitda),
                    ps=_mul(ps),
                    roe=_pct(roe),
                    roic=_pct(roic),
                    gross_margin=_pct(gross_margin),
                    ebit_margin=_pct(ebit_margin),
                    net_margin=_pct(net_margin),
                    dividend_yield=_pct(dy),
                    payout=_pct(payout),
                    net_debt_ebitda=_mul(nde),
                    debt_equity=_mul(de),
                    raw=raw
                )
                # sanity: se quase tudo None, considera falha
                if any([resp.pe, resp.pb, resp.ev_ebitda, resp.roe, resp.net_margin, resp.dividend_yield]):
                    return resp
            except Exception:
                continue
    return None

# -------------------------
# Fundamentus (B3) — scraping robusto por rótulo
# -------------------------
async def _fetch_fundamentus(ticker: str) -> Optional[FundamentalsResponse]:
    tk = ticker.replace(".SA", "").upper()
    url = f"http://www.fundamentus.com.br/detalhes.php?papel={tk}"
    try:
        async with httpx.AsyncClient(timeout=T_OUT, headers=HEADERS) as client:
            r = await client.get(url)
            if r.status_code != 200 or not r.text:
                return None
            soup = BeautifulSoup(r.text, "lxml")

            def find_value(label_pt: str) -> Optional[float]:
                lab = soup.find(string=re.compile(label_pt, re.I))
                if not lab:
                    return None
                tr = lab.find_parent("td")
                if not tr:
                    return None
                val_td = tr.find_next_sibling("td")
                if not val_td:
                    return None
                return _to_float(val_td.get_text(strip=True))

            pe = find_value(r"P\/L")
            pb = find_value(r"P\/VPA")
            ps = find_value(r"P\/SR")
            ev_ebitda = find_value(r"EV\/EBITDA")
            roe = find_value(r"ROE")
            roic = find_value(r"ROIC")
            gross_margin = find_value(r"Marg\. Bruta")
            ebit_margin = find_value(r"Marg\. EBIT")
            net_margin = find_value(r"Marg\. Líquida")
            dy = find_value(r"Div\. Yield")
            nde = find_value(r"Dívida Líquida\/EBITDA")
            de = find_value(r"Dívida Bruta\/Patrim\. Líquido")

            return FundamentalsResponse(
                ticker=ticker,
                source="fundamentus",
                confidence="medium",
                updated_at=_now(),
                pe=_mul(pe),
                pb=_mul(pb),
                ev_ebitda=_mul(ev_ebitda),
                ps=_mul(ps),
                roe=_pct(roe),
                roic=_pct(roic),
                gross_margin=_pct(gross_margin),
                ebit_margin=_pct(ebit_margin),
                net_margin=_pct(net_margin),
                dividend_yield=_pct(dy),
                net_debt_ebitda=_mul(nde),
                debt_equity=_mul(de),
                raw={"url": url}
            )
    except Exception:
        return None

# -------------------------
# Yahoo Finance (BR/US) — rápido e estável
# -------------------------
def _from_yf_info(symbol: str) -> Optional[FundamentalsResponse]:
    try:
        t = yf.Ticker(symbol)
        i = t.info  # pode falhar sob rate-limit, mas em geral funciona pra fundamentals
        if not i:
            return None

        def g(key):
            return i.get(key, None)

        pe = g("trailingPE")
        pb = g("priceToBook")
        ev_ebitda = g("enterpriseToEbitda")
        ps = g("priceToSalesTrailing12Months")
        roe = (g("returnOnEquity") or 0) * 100 if g("returnOnEquity") is not None else None
        roa = (g("returnOnAssets") or 0) * 100 if g("returnOnAssets") is not None else None
        gross_margin = (g("grossMargins") or 0) * 100 if g("grossMargins") is not None else None
        op_margin = (g("operatingMargins") or 0) * 100 if g("operatingMargins") is not None else None
        net_margin = (g("profitMargins") or 0) * 100 if g("profitMargins") is not None else None
        dy = (g("dividendYield") or 0) * 100 if g("dividendYield") is not None else None

        return FundamentalsResponse(
            ticker=symbol,
            source="yahoo",
            confidence="medium",
            updated_at=_now(),
            pe=_mul(pe),
            pb=_mul(pb),
            ev_ebitda=_mul(ev_ebitda),
            ps=_mul(ps),
            roe=_pct(roe),
            roa=_pct(roa),
            gross_margin=_pct(gross_margin),
            ebit_margin=_pct(op_margin),
            net_margin=_pct(net_margin),
            dividend_yield=_pct(dy),
            raw={"keys": ["trailingPE","priceToBook","enterpriseToEbitda","priceToSalesTrailing12Months",
                          "returnOnEquity","returnOnAssets","grossMargins","operatingMargins","profitMargins","dividendYield"]}
        )
    except Exception:
        return None

# -------------------------
# API pública do módulo
# -------------------------
async def get_fundamentals(ticker: str) -> Dict:
    """
    Estratégia:
      1) Se BR (.SA): StatusInvest → Fundamentus → Yahoo
      2) Se US/Outros: Yahoo direto
    Resposta sempre 200 com confidence e source.
    """
    symbol = ticker.upper().strip()
    is_b3 = symbol.endswith(".SA") or (len(symbol) == 5 and symbol.isalpha())

    if not symbol.endswith(".SA") and is_b3:
        symbol = f"{symbol}.SA"

    resp: Optional[FundamentalsResponse] = None

    if symbol.endswith(".SA"):
        resp = await _fetch_statusinvest(symbol)
        if not resp:
            resp = await _fetch_fundamentus(symbol)
        if not resp:
            resp = _from_yf_info(symbol)
    else:
        resp = _from_yf_info(symbol)

    if not resp:
        resp = FundamentalsResponse(
            ticker=symbol,
            source="none",
            confidence="low",
            updated_at=_now(),
            raw={}
        )

    return json.loads(resp.model_dump_json())

