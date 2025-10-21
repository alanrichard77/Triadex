from pydantic import BaseModel, Field
from typing import Optional, Dict

class Ratio(BaseModel):
    value: Optional[float] = Field(None, description="Valor numérico normalizado")
    unit: Optional[str] = Field(None, description="Unidade quando aplicável (%, x, R$)")

class FundamentalsResponse(BaseModel):
    ticker: str
    source: str
    confidence: str
    updated_at: str

    # valuation
    pe: Ratio | None = None               # P/L
    pb: Ratio | None = None               # P/VPA
    ev_ebitda: Ratio | None = None        # EV/EBITDA
    ev_ebit: Ratio | None = None          # EV/EBIT
    ps: Ratio | None = None               # P/S (Receita)

    # profitability / returns
    roe: Ratio | None = None              # %
    roic: Ratio | None = None             # %
    roa: Ratio | None = None              # %
    gross_margin: Ratio | None = None     # %
    ebit_margin: Ratio | None = None      # %
    net_margin: Ratio | None = None       # %

    # leverage
    net_debt_ebitda: Ratio | None = None  # x
    debt_equity: Ratio | None = None      # x

    # dividends / growth
    dividend_yield: Ratio | None = None   # %
    payout: Ratio | None = None           # %
    revenue_cagr_5y: Ratio | None = None  # %
    eps_cagr_5y: Ratio | None = None      # %

    raw: Dict | None = None               # payload bruto (debug/observabilidade)

