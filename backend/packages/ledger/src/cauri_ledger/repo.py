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
from cauri_ledger.models import CatalogAsset, DuplicateCandidate, FixedIncomeDraft
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


def catalog_assets(conn: Conn, tickers: Collection[str]) -> dict[str, CatalogAsset]:
    if not tickers:
        return {}
    rows = conn.execute(
        "select ticker, class, name, maturity_date, active from market.assets"
        " where ticker = any(%s)",
        [list(tickers)],
    ).fetchall()
    return {r["ticker"]: _catalog(r) for r in rows}


def tesouro_assets(conn: Conn) -> list[CatalogAsset]:
    rows = conn.execute(
        "select ticker, class, name, maturity_date, active from market.assets"
        " where class = 'tesouro' order by maturity_date, ticker"
    ).fetchall()
    return [_catalog(r) for r in rows]


def _catalog(row: Mapping[str, Any]) -> CatalogAsset:
    return CatalogAsset(
        ticker=row["ticker"],
        asset_class=AssetClass(row["class"]),
        name=row["name"],
        maturity_date=row["maturity_date"],
        active=row["active"],
    )


def indicator_values(conn: Conn, series: str, since: date, until: date) -> dict[date, Decimal]:
    rows = conn.execute(
        "select ref_date, value from market.indicators"
        " where series = %s and ref_date between %s and %s",
        [series, since, until],
    ).fetchall()
    return {r["ref_date"]: r["value"] for r in rows}


def closes_brl(
    conn: Conn, tickers: Collection[str], since: date, until: date
) -> dict[str, dict[date, Decimal]]:
    if not tickers:
        return {}
    rows = conn.execute(
        "select a.ticker, p.price_date, p.close from market.prices_daily p"
        " join market.assets a on a.id = p.asset_id"
        " where a.ticker = any(%s) and p.currency = 'BRL' and p.price_date between %s and %s",
        [list(tickers), since, until],
    ).fetchall()
    out: dict[str, dict[date, Decimal]] = {}
    for r in rows:
        out.setdefault(r["ticker"], {})[r["price_date"]] = r["close"]
    return out


def alias_target(conn: Conn, alias_norm: str) -> tuple[str, str] | None:
    """("issuer", "PETR") ou ("asset", "BTC") para um apelido já normalizado."""
    row = conn.execute(
        "select l.issuer_code, a.ticker from market.asset_aliases l"
        " left join market.assets a on a.id = l.asset_id where l.alias_norm = %s",
        [alias_norm],
    ).fetchone()
    if row is None:
        return None
    if row["issuer_code"]:
        return "issuer", row["issuer_code"]
    return "asset", row["ticker"]


def issuer_assets(conn: Conn, issuer_code: str) -> list[CatalogAsset]:
    rows = conn.execute(
        "select ticker, class, name, maturity_date, active from market.assets"
        " where issuer_code = %s and active order by ticker",
        [issuer_code],
    ).fetchall()
    return [_catalog(r) for r in rows]


def last_close_brl(conn: Conn, ticker: str, on: date) -> tuple[Decimal, date] | None:
    row = conn.execute(
        "select p.close, p.price_date from market.prices_daily p"
        " join market.assets a on a.id = p.asset_id"
        " where a.ticker = %s and p.currency = 'BRL' and p.price_date <= %s"
        " order by p.price_date desc limit 1",
        [ticker, on],
    ).fetchone()
    return (row["close"], row["price_date"]) if row else None


def recent_brokers(conn: Conn, user_id: UUID, asset_class: str | None) -> list[str]:
    """Corretoras das movimentações mais recentes do usuário (da classe, se informada)."""
    rows = conn.execute(
        "select broker_id, max(created_at) as last from ledger.movements"
        " where user_id = %s and voided_at is null and (%s::text is null or asset_class::text = %s)"
        " group by broker_id order by last desc limit 5",
        [user_id, asset_class, asset_class],
    ).fetchall()
    return [r["broker_id"] for r in rows]


def all_brokers(conn: Conn) -> dict[str, str]:
    rows = conn.execute("select id, name from market.brokers order by name").fetchall()
    return {r["id"]: r["name"] for r in rows}


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
    " amount, factor, income_kind, origin, origin_label, idempotency_key, voided_at, notes,"
    " opening_balance"
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
        opening_balance=row["opening_balance"],
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


def active_movements_by_ids(conn: Conn, user_id: UUID, ids: Collection[UUID]) -> list[Movement]:
    if not ids:
        return []
    rows = conn.execute(
        f"select {_MOVEMENT_COLUMNS} from ledger.movements"
        " where user_id = %s and voided_at is null and id = any(%s)",
        [user_id, list(ids)],
    ).fetchall()
    return [to_movement(r, 0) for r in rows]


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
    *,
    source_prefix: str | None = None,
    exclude_ids: Collection[UUID] = (),
) -> list[DuplicateCandidate]:
    """Mesma operação já gravada por outra origem: mesmo ativo, data, tipo e quantidade
    (ou valor, para aporte, resgate e provento; ou fator, para eventos).

    "Outra origem" é outro canal (manual, chat, importação). Com ``source_prefix``, que
    as importações usam, é tudo o que não veio da mesma fonte: a B3 e a planilha genérica
    são importações as duas, mas uma pode repetir a outra.
    """
    target_column = "asset_id" if movement.asset_id is not None else "instrument_id"
    if movement.type in {MovementType.COMPRA, MovementType.VENDA}:
        measure_column, measure = "quantity", movement.quantity
    elif movement.factor is not None:
        measure_column, measure = "factor", movement.factor
    else:
        measure_column, measure = "amount", movement.amount
    if source_prefix is None:
        other_source, other_value = "origin <> %s", origin.value
    else:
        other_source, other_value = "not starts_with(idempotency_key, %s)", source_prefix
    rows = conn.execute(
        "select id, origin, origin_label, trade_date from ledger.movements"
        f" where user_id = %s and voided_at is null and {other_source}"
        "   and idempotency_key <> %s and not (id = any(%s))"
        f"   and {target_column} = %s and trade_date = %s and type = %s and {measure_column} = %s"
        " order by created_at, id",
        [
            user_id,
            other_value,
            idempotency_key,
            list(exclude_ids),
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
