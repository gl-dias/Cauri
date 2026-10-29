"""Rascunho de movimentação <-> JSON guardado na linha da pré-visualização.

Números viajam como texto, para nunca passarem por float.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from cauri_core import FiKind, IncomeKind, MovementType
from cauri_ledger import FixedIncomeDraft, MovementDraft


def _num(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def to_json(d: MovementDraft) -> dict[str, Any]:
    fi = d.fixed_income
    return {
        "idempotency_key": d.idempotency_key,
        "trade_date": d.trade_date.isoformat(),
        "type": d.type.value,
        "broker_id": d.broker_id,
        "ticker": d.ticker,
        "fixed_income": None
        if fi is None
        else {
            "kind": fi.kind.value,
            "issuer_name": fi.issuer_name,
            "rate_pct": _num(fi.rate_pct),
            "maturity_date": fi.maturity_date.isoformat(),
            "label": fi.label,
        },
        "quantity": _num(d.quantity),
        "unit_price": _num(d.unit_price),
        "fees": _num(d.fees),
        "amount": _num(d.amount),
        "factor": _num(d.factor),
        "income_kind": d.income_kind.value if d.income_kind else None,
        "notes": d.notes,
        "origin_label": d.origin_label,
    }


def from_json(data: Mapping[str, Any]) -> MovementDraft:
    fi = data.get("fixed_income")
    return MovementDraft(
        idempotency_key=data["idempotency_key"],
        trade_date=date.fromisoformat(data["trade_date"]),
        type=MovementType(data["type"]),
        broker_id=data["broker_id"],
        ticker=data.get("ticker"),
        fixed_income=None
        if fi is None
        else FixedIncomeDraft(
            kind=FiKind(fi["kind"]),
            issuer_name=fi["issuer_name"],
            rate_pct=Decimal(fi["rate_pct"]),
            maturity_date=date.fromisoformat(fi["maturity_date"]),
            label=fi.get("label"),
        ),
        quantity=_dec(data.get("quantity")),
        unit_price=_dec(data.get("unit_price")),
        fees=_dec(data.get("fees")) or Decimal(0),
        amount=_dec(data.get("amount")),
        factor=_dec(data.get("factor")),
        income_kind=IncomeKind(data["income_kind"]) if data.get("income_kind") else None,
        notes=data.get("notes"),
        origin_label=data.get("origin_label"),
    )
