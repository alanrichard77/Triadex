from datetime import datetime, timezone, timedelta

# Helper para converter timestamps em ISO São Paulo, se necessário
def to_iso_brt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # America/Sao_Paulo é -03 fixo na maior parte do ano, simplificação
    return (dt.astimezone(timezone(timedelta(hours=-3)))).isoformat()

