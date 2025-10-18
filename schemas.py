from typing import Optional, List
from pydantic import BaseModel

class ResolvedSymbol(BaseModel):
    symbol: str
    exchange: str
    name: str

class QuoteOutPrice(BaseModel):
    last: Optional[float]
    change_pct: Optional[float]
    currency: Optional[str]
    asof: Optional[str]
    source: str

class QuoteOutMarketCap(BaseModel):
    value: Optional[float]
    currency: Optional[str]

class QuoteOutVolume(BaseModel):
    value: Optional[float]

class QuoteOutStatus(BaseModel):
    confidence: str
    notes: List[str]

class QuoteOut(BaseModel):
    ticker_in: str
    resolved: ResolvedSymbol
    price: QuoteOutPrice
    market_cap: QuoteOutMarketCap
    volume: QuoteOutVolume
    status: QuoteOutStatus

class HealthOut(BaseModel):
    status: str
    time_utc: str

# Representação interna antes do empacotamento final
class QuoteInternal(BaseModel):
    price: QuoteOutPrice
    market_cap: QuoteOutMarketCap
    volume: QuoteOutVolume
    status: QuoteOutStatus

