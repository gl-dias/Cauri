"""SQL do ledger. Roda na conexão recebida: na API, já com o RLS do usuário."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from cauri_core import (
    AssetClass,
    FiKind,
    FixedIncomeTerms,
    IncomeKind,
    Movement,
    MovementType,
    Origin,
)
from cauri_ledger.models import DuplicateCandidate, FixedIncomeDraft
from cauri_storage import Conn


@dataclass(frozen=True, slots=True)
class AssetRef:
    id: UUID
    ticker: str
    asset_class: AssetClass
    active: bool


def find_assets(conn: Conn, tickers: Collection[str]) -> dict[str, AssetRef]:
    if not tickers:
        return {}
    rows = conn.execute(
        "select id, ticker, class, active from market.assets where ticker = any(%s)",
        [list(tickers)],
    ).fetchall()
    return {
        r["ticker"]: AssetRef(r["id"], r["ticker"], AssetClass(r["class"]), r["active"])
        for r in rows
    }


def find_assets_by_id(conn: Conn, ids: Collection[UUID]) -> dict[UUID, AssetRef]:
    if not ids:
        return {}
    rows = conn.execute(
        "select id, ticker, class, active from market.assets where id = any(%s)", [list(ids)]
    ).fetchall()
    return {
        r["id"]: AssetRef(r["id"], r["ticker"], AssetClass(r["class"]), r["active"]) for r in rows
    }


def find_brokers(conn: Conn, ids: Collection[str]) -> set[str]:
    if not ids:
        return set()
    rows = conn.execute("select id from market.brokers where id = any(%s)", [list(ids)]).fetchall()
    return {r["id"] for r in rows}


def _terms(row: Mapping[str, Any]) -> FixedIncomeTerms:
    return FixedIncomeTerms(
        id=row["id"],
        kind=FiKind(row["kind"]),
        issuer_name=row["issuer_name"],
        rate_pct=row["rate_pct"],
        maturity_date=row["maturity_date"],
        broker_id=row["broker_id"],
        label=row["label"],
    )


def get_instruments(
    conn: Conn, user_id: UUID, ids: Collection[UUID]
) -> dict[UUID, FixedIncomeTerms]:
    if not ids:
        return {}
    rows = conn.execute(
        "select id, kind, issuer_name, rate_pct, maturity_date, broker_id, label"
        " from ledger.fi_instruments where user_id = %s and id = any(%s)",
        [user_id, list(ids)],
    ).fetchall()
    return {r["id"]: _terms(r) for r in rows}


def find_instrument_by_terms(
    conn: Conn, user_id: UUID, fi: FixedIncomeDraft, broker_id: str
) -> FixedIncomeTerms | None:
    row = conn.execute(
        "select id, kind, issuer_name, rate_pct, maturity_date, broker_id, label"
        " from ledger.fi_instruments"
        " where user_id = %s and kind = %s and issuer_name = %s and rate_pct = %s"
        "   and maturity_date = %s and broker_id = %s",
        [user_id, fi.kind.value, fi.issuer_name.strip(), fi.rate_pct, fi.maturity_date, broker_id],
    ).fetchone()
    return _terms(row) if row else None


def upsert_instrument(conn: Conn, user_id: UUID, fi: FixedIncomeDraft, broker_id: str) -> UUID:
    row = conn.execute(
        "insert into ledger.fi_instruments"
        " (user_id, kind, issuer_name, rate_pct, maturity_date, broker_id, label)"
        " values (%s, %s, %s, %s, %s, %s, %s)"
        " on conflict (user_id, kind, issuer_name, rate_pct, maturity_date, broker_id)"
        " do update set label = ledger.fi_instruments.label"
        " returning id",
        [
            user_id,
            fi.kind.value,
            fi.issuer_name.strip(),
            fi.rate_pct,
            fi.maturity_date,
            broker_id,
            fi.display_label(),
        ],
    ).fetchone()
    assert row is not None
    result: UUID = row["id"]
    return result


def existing_keys(conn: Conn, user_id: UUID, keys: Collection[str]) -> dict[str, UUID]:
    if not keys:
        return {}
    rows = conn.execute(
        "select idempotency_key, id from ledger.movements"
        " where user_id = %s and idempotency_key = any(%s)",
        [user_id, list(keys)],
    ).fetchall()
    return {r["idempotency_key"]: r["id"] for r in rows}


_MOVEMENT_COLUMNS = (
    "id, trade_date, type, broker_id, asset_id, instrument_id, quantity, unit_price, fees,"
    " amount, factor, income_kind, origin, origin_label, idempotency_key, voided_at, notes"
)


def to_movement(row: Mapping[str, Any], seq: int) -> Movement:
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
    )


def active_movements(
    conn: Conn, user_id: UUID, asset_ids: Collection[UUID], instrument_ids: Collection[UUID]
) -> list[Movement]:
    """Movimentações ativas dos ativos/títulos pedidos, com ``seq`` na ordem de criação."""
    if not asset_ids and not instrument_ids:
        return []
    rows = conn.execute(
        f"select {_MOVEMENT_COLUMNS} from ledger.movements"
        " where user_id = %s and voided_at is null"
        "   and (asset_id = any(%s) or instrument_id = any(%s))"
        " order by created_at, id",
        [user_id, list(asset_ids), list(instrument_ids)],
    ).fetchall()
    return [to_movement(r, i) for i, r in enumerate(rows)]


def get_movement(conn: Conn, user_id: UUID, movement_id: UUID) -> dict[str, Any] | None:
    return conn.execute(
        f"select {_MOVEMENT_COLUMNS} from ledger.movements where user_id = %s and id = %s",
        [user_id, movement_id],
    ).fetchone()


def duplicate_candidates(
    conn: Conn,
    user_id: UUID,
    origin: Origin,
    idempotency_key: str,
    movement: Movement,
) -> list[DuplicateCandidate]:
    """Mesma operação já gravada por outra origem: mesmo ativo, data, tipo e quantidade
    (ou valor, para aporte, resgate e provento; ou fator, para eventos)."""
    target_column = "asset_id" if movement.asset_id is not None else "instrument_id"
    if movement.type in {MovementType.COMPRA, MovementType.VENDA}:
        measure_column, measure = "quantity", movement.quantity
    elif movement.factor is not None:
        measure_column, measure = "factor", movement.factor
    else:
        measure_column, measure = "amount", movement.amount
    rows = conn.execute(
        "select id, origin, origin_label, trade_date from ledger.movements"
        " where user_id = %s and voided_at is null and origin <> %s and idempotency_key <> %s"
        f"   and {target_column} = %s and trade_date = %s and type = %s and {measure_column} = %s",
        [
            user_id,
            origin.value,
            idempotency_key,
            movement.position_key,
            movement.trade_date,
            movement.type.value,
            measure,
        ],
    ).fetchall()
    return [
        DuplicateCandidate(r["id"], Origin(r["origin"]), r["origin_label"], r["trade_date"])
        for r in rows
    ]


def cdi_rates(conn: Conn, since: date) -> dict[date, Decimal]:
    rows = conn.execute(
        "select ref_date, value from market.indicators where series = 'CDI' and ref_date >= %s",
        [since],
    ).fetchall()
    return {r["ref_date"]: r["value"] for r in rows}


def insert_movement(conn: Conn, user_id: UUID, values: Mapping[str, Any]) -> UUID | None:
    """Insere; devolve ``None`` se a chave de idempotência já existia (corrida)."""
    columns = ["user_id", *values.keys()]
    placeholders = ", ".join(["%s"] * len(columns))
    row = conn.execute(
        f"insert into ledger.movements ({', '.join(columns)}) values ({placeholders})"
        " on conflict (user_id, idempotency_key) do nothing returning id",
        [user_id, *values.values()],
    ).fetchone()
    return row["id"] if row else None


def set_change_reason(conn: Conn, reason: str | None) -> None:
    conn.execute("select set_config('cauri.change_reason', %s, true)", [reason or ""])


_EDITABLE = frozenset(
    {
        "trade_date",
        "asset_id",
        "broker_id",
        "quantity",
        "unit_price",
        "fees",
        "amount",
        "factor",
        "income_kind",
        "notes",
    }
)


def update_movement(
    conn: Conn, user_id: UUID, movement_id: UUID, values: Mapping[str, Any]
) -> None:
    unknown = set(values) - _EDITABLE
    if unknown:
        raise ValueError(f"campos não editáveis: {sorted(unknown)}")
    if not values:
        return
    assignments = ", ".join(f"{column} = %s" for column in values)
    conn.execute(
        f"update ledger.movements set {assignments} where user_id = %s and id = %s",
        [*values.values(), user_id, movement_id],
    )


def void_movement(conn: Conn, user_id: UUID, movement_id: UUID, reason: str) -> None:
    conn.execute(
        "update ledger.movements set voided_at = now(), void_reason = %s"
        " where user_id = %s and id = %s and voided_at is null",
        [reason, user_id, movement_id],
    )


def asset_ids_of(movements: Iterable[Movement]) -> set[UUID]:
    return {m.asset_id for m in movements if m.asset_id is not None}
