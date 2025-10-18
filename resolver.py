from dataclasses import dataclass
import re

from schemas import ResolvedSymbol

# Heurística simples para B3: se parecer ação brasileira, aplica sufixo .SA
# Lista rápida de endings comuns da B3
_B3_SUFFIXES = {"3", "4", "5", "6", "11", "34", "33", "32"}

# Mapas de exceções conhecidas
_EXCEPTIONS = {
    "IBOV": ResolvedSymbol(symbol="^BVSP", exchange="B3", name="Ibovespa"),
    "WIN": ResolvedSymbol(symbol="^BVSP", exchange="B3", name="Ibovespa"),  # placeholder para índice
}

def _looks_b3_stock(s: str) -> bool:
    s = s.upper()
    # padrões como PETR4, VALE3, BOVA11 etc
    return bool(re.fullmatch(r"[A-Z]{4}\d{1,2}", s))

def resolve_symbol(q: str):
    """
    Normaliza o input e tenta resolver:
      - B3: adiciona .SA no padrão Yahoo se necessário
      - Exceções mapeadas
      - Mantém símbolos EUA e ETFs como estão
    """
    raw = q.strip()
    u = raw.upper()

    if u in _EXCEPTIONS:
        rs = _EXCEPTIONS[u]
        return raw, rs

    if _looks_b3_stock(u) and not u.endswith(".SA"):
        # Padrão Yahoo para B3
        sym = f"{u}.SA"
        return raw, ResolvedSymbol(symbol=sym, exchange="B3", name=u)

    # ETFs B3 como IVVB11
    if u.endswith("11") and not u.endswith(".SA"):
        return raw, ResolvedSymbol(symbol=f"{u}.SA", exchange="B3", name=u)

    # Se o usuário passar .SA, mantém
    if u.endswith(".SA"):
        return raw, ResolvedSymbol(symbol=u, exchange="B3", name=u.replace(".SA", ""))

    # Caso geral, mantém como veio, assume USA por padrão
    return raw, ResolvedSymbol(symbol=u, exchange="AUTO", name=u)

