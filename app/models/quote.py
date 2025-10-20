from pydantic import BaseModel
from typing import Optional, Dict

class PriceInfo(BaseModel):
    last: Optional[float]
    change_pct: Optional[float]
    currency: Optional[str]
    source: str

class QuoteResponse(BaseModel):
    ticker: str
    name: Optional[str]
    price: PriceInfo
    market_cap: Optional[float]
    volume: Optional[float]
    updated_at: str
    confidence: str
    notes: Optional[str]

