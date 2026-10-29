"""Formulário de lançamento manual: texto como o usuário digitou, rascunho para o ledger.

Os números chegam como texto (``"1.234,56"`` ou ``"1234.56"``) para nunca passarem
por float no caminho. A chave de idempotência vem do front, uma por formulário
aberto: clique duplo em "Salvar" não duplica a movimentação.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from cauri_core import FiKind, IncomeKind, MovementType
from cauri_core.money import parse_br_decimal
from cauri_ledger import FixedIncomeDraft, MovementDraft, MovementPatch


class FormError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


@dataclass(frozen=True, slots=True)
class ManualEntryForm:
    client_key: str
    type: MovementType
    trade_date: date
    broker_id: str
    ticker: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    fees: str | None = None
    amount: str | None = None
    factor: str | None = None
    income_kind: IncomeKind | None = None
    instrument_id: UUID | None = None
    fi_kind: FiKind | None = None
    fi_issuer: str | None = None
    fi_rate_pct: str | None = None
    fi_maturity: date | None = None
    fi_label: str | None = None
    notes: str | None = None
    # Saldo inicial: compra marcada, com o custo médio da posição anterior ao histórico.
    opening_balance: bool = False


@dataclass(frozen=True, slots=True)
class ManualPatchForm:
    trade_date: date | None = None
    ticker: str | None = None
    broker_id: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    fees: str | None = None
    amount: str | None = None
    factor: str | None = None
    income_kind: IncomeKind | None = None
    notes: str | None = None


def _number(field: str, text: str | None) -> Decimal | None:
    if text is None or not text.strip():
        return None
    try:
        return parse_br_decimal(text)
    except ValueError as exc:
        raise FormError(field, f"Número inválido: {text!r}.") from exc


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def to_draft(form: ManualEntryForm) -> MovementDraft:
    key = form.client_key.strip()
    if len(key) < 8:
        raise FormError("client_key", "Identificador do formulário inválido.")

    fixed_income: FixedIncomeDraft | None = None
    has_fi_terms = any(
        v is not None
        for v in (form.fi_kind, _clean(form.fi_issuer), _clean(form.fi_rate_pct), form.fi_maturity)
    )
    if has_fi_terms:
        if form.fi_kind is None:
            raise FormError("fi_kind", "Informe o tipo do título (CDB, LCI ou LCA).")
        issuer = _clean(form.fi_issuer)
        if issuer is None:
            raise FormError("fi_issuer", "Informe o emissor do título.")
        rate = _number("fi_rate_pct", form.fi_rate_pct)
        if rate is None:
            raise FormError("fi_rate_pct", "Informe o percentual do CDI.")
        if form.fi_maturity is None:
            raise FormError("fi_maturity", "Informe o vencimento.")
        fixed_income = FixedIncomeDraft(
            kind=form.fi_kind,
            issuer_name=issuer,
            rate_pct=rate,
            maturity_date=form.fi_maturity,
            label=_clean(form.fi_label),
        )

    ticker = _clean(form.ticker)
    return MovementDraft(
        idempotency_key=f"manual:{key}",
        trade_date=form.trade_date,
        type=form.type,
        broker_id=form.broker_id.strip(),
        ticker=ticker.upper() if ticker else None,
        fixed_income=fixed_income,
        instrument_id=form.instrument_id,
        quantity=_number("quantity", form.quantity),
        unit_price=_number("unit_price", form.unit_price),
        fees=_number("fees", form.fees) or Decimal(0),
        amount=_number("amount", form.amount),
        factor=_number("factor", form.factor),
        income_kind=form.income_kind,
        notes=_clean(form.notes),
        origin_label="Saldo inicial" if form.opening_balance else None,
        opening_balance=form.opening_balance,
    )


def to_patch(form: ManualPatchForm) -> MovementPatch:
    ticker = _clean(form.ticker)
    return MovementPatch(
        trade_date=form.trade_date,
        ticker=ticker.upper() if ticker else None,
        broker_id=_clean(form.broker_id),
        quantity=_number("quantity", form.quantity),
        unit_price=_number("unit_price", form.unit_price),
        fees=_number("fees", form.fees),
        amount=_number("amount", form.amount),
        factor=_number("factor", form.factor),
        income_kind=form.income_kind,
        notes=form.notes,
    )
