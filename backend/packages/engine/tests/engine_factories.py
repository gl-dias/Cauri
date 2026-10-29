"""Atalhos para montar movimentações nos testes."""

from __future__ import annotations

import itertools
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from cauri_core import IncomeKind, Movement, MovementType

_seq = itertools.count()

ASSET_A = UUID("10000000-0000-4000-8000-000000000001")
ASSET_B = UUID("10000000-0000-4000-8000-000000000002")
INSTRUMENT = UUID("20000000-0000-4000-8000-000000000001")


def D(value: str | int) -> Decimal:  # noqa: N802 - atalho de teste
    return Decimal(value)


def buy(
    day: date,
    qty: str | int,
    price: str | int,
    fees: str | int = 0,
    asset: UUID = ASSET_A,
    broker: str = "corretora-a",
) -> Movement:
    return Movement(
        id=uuid4(),
        trade_date=day,
        type=MovementType.COMPRA,
        broker_id=broker,
        asset_id=asset,
        quantity=D(qty),
        unit_price=D(price),
        fees=D(fees),
        seq=next(_seq),
    )


def sell(
    day: date,
    qty: str | int,
    price: str | int,
    fees: str | int = 0,
    asset: UUID = ASSET_A,
    broker: str = "corretora-a",
) -> Movement:
    return Movement(
        id=uuid4(),
        trade_date=day,
        type=MovementType.VENDA,
        broker_id=broker,
        asset_id=asset,
        quantity=D(qty),
        unit_price=D(price),
        fees=D(fees),
        seq=next(_seq),
    )


def event(
    day: date,
    kind: MovementType,
    factor: str,
    unit_cost: str | None = None,
    asset: UUID = ASSET_A,
) -> Movement:
    return Movement(
        id=uuid4(),
        trade_date=day,
        type=kind,
        broker_id="corretora-a",
        asset_id=asset,
        factor=D(factor),
        unit_price=D(unit_cost) if unit_cost is not None else None,
        seq=next(_seq),
    )


def income(day: date, amount: str, asset: UUID = ASSET_A, broker: str = "corretora-a") -> Movement:
    return Movement(
        id=uuid4(),
        trade_date=day,
        type=MovementType.PROVENTO,
        broker_id=broker,
        asset_id=asset,
        amount=D(amount),
        income_kind=IncomeKind.DIVIDENDO,
        seq=next(_seq),
    )


def deposit(day: date, amount: str, instrument: UUID = INSTRUMENT) -> Movement:
    return Movement(
        id=uuid4(),
        trade_date=day,
        type=MovementType.APORTE,
        broker_id="banco-x",
        instrument_id=instrument,
        amount=D(amount),
        seq=next(_seq),
    )


def redeem(day: date, amount: str, instrument: UUID = INSTRUMENT) -> Movement:
    return Movement(
        id=uuid4(),
        trade_date=day,
        type=MovementType.RESGATE,
        broker_id="banco-x",
        instrument_id=instrument,
        amount=D(amount),
        seq=next(_seq),
    )
