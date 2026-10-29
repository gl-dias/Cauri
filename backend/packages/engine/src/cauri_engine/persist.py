"""Lê o ledger e o mercado, calcula os snapshots (núcleo puro) e grava.

Recalcular é sempre a partir da primeira movimentação (o estado de cada dia depende
de todo o passado), mas só os dias a partir de ``from_date`` são regravados.

Quem chama decide a conexão: a API usa a do usuário (RLS: só o próprio), o job usa a
do ``cauri_ingest`` (todas as carteiras, inclusive a demo).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from cauri_core import AssetClass, FiKind, FixedIncomeTerms, IncomeKind, Movement, MovementType
from cauri_core.calendar import b3_trading_days, is_b3_trading_day, previous_trading_day
from cauri_core.dates import now_sp
from cauri_core.session import market_close
from cauri_engine.calc import (
    AssetInfo,
    CdiCurve,
    DaySnapshot,
    PortfolioInputs,
    PriceBook,
    compute_snapshots,
)
from cauri_storage import Conn

# Margem depois do fim do pregão até o fechamento chegar pela fonte gratuita.
CLOSE_AVAILABLE_AFTER = timedelta(minutes=30)
# O job regrava os últimos dias para absorver dados que chegam atrasados (PU do Tesouro
# de D-1, CDI de D-1, correções de fonte).
DAILY_LOOKBACK = timedelta(days=7)


def last_closed_day(now: datetime | None = None) -> date:
    """Último pregão com fechamento disponível: hoje depois do fechamento, senão o anterior."""
    moment = now or now_sp()
    today = moment.date()
    if is_b3_trading_day(today) and moment >= market_close(today) + CLOSE_AVAILABLE_AFTER:
        return today
    return previous_trading_day(today)


def _movement(row: dict[str, Any], seq: int) -> Movement:
    return Movement(
        id=row["id"],
        trade_date=row["trade_date"],
        type=MovementType(row["type"]),
        broker_id=row["broker_id"],
        asset_id=row["asset_id"],
        instrument_id=row["instrument_id"],
        quantity=row["quantity"],
        unit_price=row["unit_price"],
        fees=row["fees"],
        amount=row["amount"],
        factor=row["factor"],
        income_kind=IncomeKind(row["income_kind"]) if row["income_kind"] else None,
        seq=seq,
        opening_balance=row["opening_balance"],
    )


def load_inputs(conn: Conn, user_id: UUID, until: date) -> PortfolioInputs | None:
    rows = conn.execute(
        "select id, trade_date, type, broker_id, asset_id, instrument_id, quantity, unit_price,"
        " fees, amount, factor, income_kind, opening_balance from ledger.movements"
        " where user_id = %s and voided_at is null and trade_date <= %s"
        " order by created_at, id",
        [user_id, until],
    ).fetchall()
    if not rows:
        return None
    movements = [_movement(r, i) for i, r in enumerate(rows)]
    asset_ids = list({m.asset_id for m in movements if m.asset_id is not None})
    instrument_ids = list({m.instrument_id for m in movements if m.instrument_id is not None})
    inception = min(m.trade_date for m in movements)

    assets = {
        r["id"]: AssetInfo(r["id"], r["ticker"], AssetClass(r["class"]))
        for r in conn.execute(
            "select id, ticker, class from market.assets where id = any(%s)", [asset_ids]
        ).fetchall()
    }
    instruments = {
        r["id"]: FixedIncomeTerms(
            id=r["id"],
            kind=FiKind(r["kind"]),
            issuer_name=r["issuer_name"],
            rate_pct=r["rate_pct"],
            maturity_date=r["maturity_date"],
            broker_id=r["broker_id"],
            label=r["label"],
        )
        for r in conn.execute(
            "select id, kind, issuer_name, rate_pct, maturity_date, broker_id, label"
            " from ledger.fi_instruments where id = any(%s)",
            [instrument_ids],
        ).fetchall()
    }
    closes: dict[UUID, dict[date, Decimal]] = defaultdict(dict)
    for r in conn.execute(
        "select asset_id, price_date, close from market.prices_daily"
        " where currency = 'BRL' and asset_id = any(%s) and price_date <= %s",
        [asset_ids, until],
    ).fetchall():
        closes[r["asset_id"]][r["price_date"]] = r["close"]
    cdi = {
        r["ref_date"]: r["value"]
        for r in conn.execute(
            "select ref_date, value from market.indicators"
            " where series = 'CDI' and ref_date >= %s and ref_date <= %s",
            [inception, until],
        ).fetchall()
    }
    ipca = {
        r["ref_date"]: r["value"]
        for r in conn.execute(
            "select ref_date, value from market.indicators"
            " where series = 'IPCA' and ref_date >= %s",
            [inception.replace(day=1)],
        ).fetchall()
    }
    return PortfolioInputs(
        movements=movements,
        assets=assets,
        instruments=instruments,
        prices=PriceBook(closes),
        cdi=CdiCurve(cdi),
        ipca_monthly=ipca,
    )


@dataclass(frozen=True, slots=True)
class RecalcResult:
    user_id: UUID
    from_date: date
    until: date
    days_written: int


def _delete_from(conn: Conn, user_id: UUID, from_date: date) -> None:
    for table in ("position_snapshots", "portfolio_snapshots", "bucket_snapshots"):
        conn.execute(
            f"delete from engine.{table} where user_id = %s and snap_date >= %s",
            [user_id, from_date],
        )


def _write(conn: Conn, user_id: UUID, snapshots: Iterable[DaySnapshot]) -> int:
    positions: list[tuple[Any, ...]] = []
    portfolio: list[tuple[Any, ...]] = []
    buckets: list[tuple[Any, ...]] = []
    for s in snapshots:
        portfolio.append(
            (
                user_id,
                s.snap_date,
                s.total.market_value,
                s.total.cost_basis,
                s.total.net_flows,
                s.total.income,
                s.total.quota_value,
                s.cdi_index,
                s.ipca_index,
                s.stale_count,
                s.cdi_equivalent,
            )
        )
        for p in s.positions:
            positions.append(
                (
                    user_id,
                    s.snap_date,
                    p.asset_id,
                    p.instrument_id,
                    p.broker_id,
                    p.asset_class.value,
                    p.quantity,
                    p.avg_cost,
                    p.cost_basis,
                    p.price,
                    p.price_date,
                    p.price_status.value,
                    p.market_value,
                    p.realized_pnl,
                    p.income_cum,
                )
            )
        for kind, mapping in (("class", s.by_class), ("broker", s.by_broker)):
            for key, b in mapping.items():
                buckets.append(
                    (
                        user_id,
                        s.snap_date,
                        kind,
                        str(key),
                        b.market_value,
                        b.cost_basis,
                        b.net_flows,
                        b.income,
                        b.quota_value,
                    )
                )
    with conn.cursor() as cur:
        cur.executemany(
            "insert into engine.portfolio_snapshots (user_id, snap_date, market_value, cost_basis,"
            " net_flows, income, quota_value, cdi_index, ipca_index, stale_count, cdi_equivalent)"
            " values (%s, %s, %s, %s, %s, %s, round(%s, 12), round(%s, 16), round(%s, 16), %s, %s)",
            portfolio,
        )
        cur.executemany(
            "insert into engine.position_snapshots (user_id, snap_date, asset_id, instrument_id,"
            " broker_id, asset_class, quantity, avg_cost, cost_basis, price, price_date,"
            " price_status, market_value, realized_pnl, income_cum)"
            " values (%s, %s, %s, %s, %s, %s, round(%s, 10), round(%s, 10), %s, %s, %s, %s, %s,"
            " %s, %s)",
            positions,
        )
        cur.executemany(
            "insert into engine.bucket_snapshots (user_id, snap_date, bucket_kind, bucket_key,"
            " market_value, cost_basis, net_flows, income, quota_value)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, round(%s, 12))",
            buckets,
        )
    return len(portfolio)


def recalc_user(conn: Conn, user_id: UUID, *, from_date: date, until: date) -> RecalcResult:
    """Recalcula e regrava os snapshots do usuário de ``from_date`` até ``until``."""
    _delete_from(conn, user_id, from_date)
    inputs = load_inputs(conn, user_id, until)
    if inputs is None:  # sem movimentações ativas: nada para mostrar a partir daqui
        return RecalcResult(user_id, from_date, until, 0)
    inception = min(m.trade_date for m in inputs.movements)
    days = list(b3_trading_days(inception, until))
    snapshots = [s for s in compute_snapshots(inputs, days) if s.snap_date >= from_date]
    return RecalcResult(user_id, from_date, until, _write(conn, user_id, snapshots))


def take_dirty(conn: Conn, user_id: UUID) -> tuple[date, datetime] | None:
    row = conn.execute(
        "select from_date, requested_at from engine.dirty_ranges where user_id = %s", [user_id]
    ).fetchone()
    return (row["from_date"], row["requested_at"]) if row else None


def clear_dirty(conn: Conn, user_id: UUID, requested_at: datetime) -> None:
    """Limpa a marca, a menos que uma mudança nova tenha chegado durante o recálculo."""
    conn.execute(
        "delete from engine.dirty_ranges where user_id = %s and requested_at <= %s",
        [user_id, requested_at],
    )


def recalc_dirty(conn: Conn, user_id: UUID, *, until: date) -> RecalcResult | None:
    """Recalcula a partir da menor data marcada pelo ledger (fluxo da API)."""
    dirty = take_dirty(conn, user_id)
    if dirty is None:
        return None
    from_date, requested_at = dirty
    result = recalc_user(conn, user_id, from_date=from_date, until=until)
    clear_dirty(conn, user_id, requested_at)
    return result


def users_for_daily(conn: Conn, day: date) -> list[tuple[UUID, date]]:
    """Todo usuário com movimentações (inclusive o demo) e de onde recalcular."""
    rows = conn.execute(
        "select u.user_id, least(d.from_date, %s) as from_date"
        " from (select distinct user_id from ledger.movements"
        "       union select user_id from engine.dirty_ranges) u"
        " left join engine.dirty_ranges d on d.user_id = u.user_id",
        [day - DAILY_LOOKBACK],
    ).fetchall()
    return [(r["user_id"], r["from_date"] or day - DAILY_LOOKBACK) for r in rows]
