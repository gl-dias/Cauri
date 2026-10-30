"""Saúde do mercado para o monitoramento: há fechamento da B3 nos últimos dias úteis?

O workflow de monitoramento roda isto de manhã nos dias úteis. Se faltam fechamentos em
``business_days`` pregões seguidos (até o último pregão já fechado), abre uma issue.
Carteira sem ação, FII nem ETF não tem o que conferir e passa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from cauri_core.calendar import b3_trading_days
from cauri_storage import Conn


@dataclass(frozen=True, slots=True)
class Health:
    ok: bool
    last_close: date | None
    missing_days: tuple[date, ...]
    message: str


def check(conn: Conn, *, until: date, business_days: int) -> Health:
    row = conn.execute(
        "select max(p.price_date) as last from market.prices_daily p"
        " join market.assets a on a.id = p.asset_id"
        " where a.class in ('acao', 'fii', 'etf') and p.currency = 'BRL' and p.price_date <= %s",
        [until],
    ).fetchone()
    last: date | None = row["last"] if row else None
    # Só importa se alguma carteira tem ação, FII ou ETF (o cadastro tem a B3 inteira).
    tracked = conn.execute(
        "select exists (select 1 from ledger.movements where voided_at is null"
        " and asset_class in ('acao', 'fii', 'etf')) as n"
    ).fetchone()
    return evaluate(last, bool(tracked and tracked["n"]), until=until, business_days=business_days)


def evaluate(last: date | None, tracked: bool, *, until: date, business_days: int) -> Health:
    """Regra pura: alerta se faltam fechamentos em ``business_days`` pregões seguidos."""
    if last is None:
        if tracked:
            return Health(False, None, (), "Nenhum fechamento de ação, FII ou ETF no banco.")
        return Health(True, None, (), "Sem ações nem FIIs para conferir.")
    missing = tuple(d for d in b3_trading_days(last, until) if d > last)
    if len(missing) >= business_days:
        days = ", ".join(f"{d:%d/%m/%Y}" for d in missing)
        return Health(
            False,
            last,
            missing,
            f"Sem fechamento da B3 há {len(missing)} pregões (desde {last:%d/%m/%Y}): {days}.",
        )
    return Health(True, last, missing, f"Último fechamento da B3: {last:%d/%m/%Y}.")
