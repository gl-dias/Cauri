"""Saldo inicial sugerido quando a importação encontra venda descoberta.

Uma venda de USDT (ou de qualquer ativo) que veio de depósito externo, de P2P ou de um
período anterior ao arquivo cai na trava de venda descoberta. Em vez de só dar erro, a
pré-visualização calcula, por ativo, quanto saldo falta e desde quando, e sugere um saldo
inicial: na data do depósito que explica o saldo (quando há um no envio) ou na véspera da
primeira venda descoberta, com o fechamento do dia como sugestão de custo médio.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from cauri_core import Movement, MovementType
from cauri_engine.calc import in_order
from cauri_importers import fx
from cauri_ledger import DraftCheck, IssueCode, Ledger, MovementDraft

ORIGIN_LABEL = "Saldo inicial"
_COST_PLACES = Decimal("1e-10")


@dataclass(frozen=True, slots=True)
class Deposit:
    coin: str
    quantity: Decimal
    day: date


@dataclass(frozen=True, slots=True)
class Suggestion:
    ticker: str
    broker_id: str
    trade_date: date
    quantity: Decimal
    first_shortfall: date  # primeira venda que fica descoberta
    unit_cost: Decimal | None  # sugestão (fechamento do dia); o usuário confirma ou troca
    cost_note: str | None
    deposit: Deposit | None  # depósito do envio que explica o saldo, quando há

    def to_json(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "broker_id": self.broker_id,
            "trade_date": self.trade_date.isoformat(),
            "quantity": _num(self.quantity),
            "first_shortfall": self.first_shortfall.isoformat(),
            "unit_cost": _num(self.unit_cost) if self.unit_cost is not None else None,
            "cost_note": self.cost_note,
            "deposit": None
            if self.deposit is None
            else {"quantity": _num(self.deposit.quantity), "day": self.deposit.day.isoformat()},
        }


def _num(value: Decimal) -> str:
    return format(value.normalize(), "f")


def suggest(
    ledger: Ledger,
    user_id: UUID,
    checked: Sequence[tuple[MovementDraft, DraftCheck]],
    deposits: Sequence[Deposit],
) -> list[Suggestion]:
    """Uma sugestão por ativo com venda descoberta, cobrindo todas as vendas dele no envio."""
    short = [(d, c) for d, c in checked if c.shortfall is not None]
    if not short:
        return []
    tickers = sorted({c.shortfall.ticker for _, c in short if c.shortfall})
    ids, existing = ledger.timeline(user_id, tickers)
    out: list[Suggestion] = []
    for ticker in tickers:
        asset_id = ids.get(ticker)
        if asset_id is None:
            continue
        # O que vai entrar: rascunhos sem erro, ou só com venda descoberta.
        drafted = [
            _movement(d, asset_id, seq=len(existing) + i)
            for i, (d, c) in enumerate(checked)
            if d.ticker == ticker
            and c.already_posted is None
            and not c.duplicates
            and all(e.code is IssueCode.OVERSELL for e in c.errors)
        ]
        lowest, first_negative = _lowest_balance(
            [m for m in existing if m.asset_id == asset_id] + drafted
        )
        if lowest >= 0 or first_negative is None:
            continue
        missing = -lowest
        broker = next(d.broker_id for d, c in short if c.shortfall and c.shortfall.ticker == ticker)
        deposit = _explaining_deposit(deposits, ticker, first_negative)
        if deposit is not None:
            when, quantity = deposit.day, max(missing, deposit.quantity)
        else:
            when, quantity = first_negative - timedelta(days=1), missing
        unit_cost, note = _suggested_cost(ledger, ticker, when)
        out.append(
            Suggestion(
                ticker=ticker,
                broker_id=broker,
                trade_date=when,
                quantity=quantity,
                first_shortfall=first_negative,
                unit_cost=unit_cost,
                cost_note=note,
                deposit=deposit,
            )
        )
    return out


def _movement(d: MovementDraft, asset_id: UUID, seq: int) -> Movement:
    return Movement(
        id=uuid4(),
        trade_date=d.trade_date,
        type=d.type,
        broker_id=d.broker_id,
        asset_id=asset_id,
        quantity=d.quantity,
        unit_price=d.unit_price,
        fees=d.fees,
        factor=d.factor,
        seq=seq,
        opening_balance=d.opening_balance,
    )


def _lowest_balance(movements: Sequence[Movement]) -> tuple[Decimal, date | None]:
    """Menor saldo ao longo do tempo e o dia em que ele fica negativo pela primeira vez."""
    balance = lowest = Decimal(0)
    first_negative: date | None = None
    for m in in_order(movements):
        if m.type is MovementType.COMPRA:
            balance += m.quantity or 0
        elif m.type is MovementType.VENDA:
            balance -= m.quantity or 0
        elif m.type in {MovementType.DESDOBRAMENTO, MovementType.GRUPAMENTO}:
            balance *= m.factor or 1
        elif m.type is MovementType.BONIFICACAO:
            balance *= 1 + (m.factor or 0)
        if balance < 0 and first_negative is None:
            first_negative = m.trade_date
        lowest = min(lowest, balance)
    return lowest, first_negative


def _explaining_deposit(deposits: Sequence[Deposit], coin: str, until: date) -> Deposit | None:
    """O depósito mais recente da moeda até a primeira venda descoberta."""
    found = [d for d in deposits if d.coin == coin and d.day <= until]
    return max(found, key=lambda d: d.day) if found else None


def _suggested_cost(ledger: Ledger, ticker: str, day: date) -> tuple[Decimal | None, str | None]:
    probe = fx.RateBook(
        ledger.indicator(fx.PTAX_SERIES, day - timedelta(days=fx.LOOKBACK_DAYS), day)
        if ticker in fx.STABLECOINS
        else {},
        ledger.closes({ticker}, day - timedelta(days=fx.LOOKBACK_DAYS), day)
        if ticker not in fx.STABLECOINS
        else {},
    )
    try:
        rate = probe.rate(ticker, day)
    except fx.ConversionError:
        return None, None
    return rate.value.quantize(_COST_PLACES), f"sugestão: {rate.describe(day)}"


def draft(
    *,
    ticker: str,
    trade_date: date,
    quantity: Decimal,
    unit_cost: Decimal,
    broker_id: str,
) -> MovementDraft:
    """Rascunho do saldo inicial. A chave sai do conteúdo: criar o mesmo saldo de novo não
    duplica (cai em "já importada")."""
    content = f"{ticker}|{trade_date}|{_num(quantity)}|{_num(unit_cost)}|{broker_id}"
    digest = hashlib.sha256(content.encode()).hexdigest()[:40]
    return MovementDraft(
        idempotency_key=f"saldo-inicial:{digest}",
        trade_date=trade_date,
        type=MovementType.COMPRA,
        broker_id=broker_id,
        ticker=ticker,
        quantity=quantity,
        unit_price=unit_cost,
        origin_label=ORIGIN_LABEL,
        opening_balance=True,
    )


def deposits_of(rows: Sequence[Mapping[str, Any] | None]) -> list[Deposit]:
    out: list[Deposit] = []
    for t in rows:
        if t and t.get("kind") == "deposito":
            out.append(Deposit(t["coin"], Decimal(t["quantity"]), date.fromisoformat(t["day"])))
    return out
