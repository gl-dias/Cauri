"""Renda fixa privada atrelada ao CDI (CDB, LCI, LCA): valor bruto, sem IR.

Cada aporte é um lote que rende desde a própria data. O valor de um lote na data D
aplica as taxas DI dos dias k com ``início <= k < D``: a taxa de um dia remunera a
passagem daquele dia para o seguinte, então no dia do aporte o valor é o principal.

Convenção de arredondamento (aproximação da usada pela B3 para CDB pós-fixado):
taxa DI diária em 8 casas (é como a série 12 do SGS publica, em %), fator diário
``1 + TDI × p`` em 16 casas, fator acumulado truncado em 16 casas, valor truncado em
centavos.

O CDI de um dia que ainda não saiu não é estimado: o rendimento para no último dia
publicado, e quem chama fica sabendo até quando rendeu.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from cauri_core import FixedIncomeTerms, Movement, MovementType
from cauri_core.money import ONE, ZERO, trunc

_PLACES_16 = Decimal(1).scaleb(-16)
HUNDRED = Decimal(100)

# Diferença aceita entre o resgate informado e o saldo bruto calculado. Cobre
# centavos de arredondamento do banco; acima disso o resgate é recusado.
REDEMPTION_TOLERANCE = Decimal("1.00")


def daily_factor(cdi_pct_per_day: Decimal, rate_pct: Decimal) -> Decimal:
    """Fator de um dia: ``cdi_pct_per_day`` em % a.d. (série 12), ``rate_pct`` em % do CDI."""
    tdi = cdi_pct_per_day / HUNDRED
    return (ONE + tdi * rate_pct / HUNDRED).quantize(_PLACES_16, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class Accrual:
    factor: Decimal
    last_rate_date: date | None  # último dia de CDI aplicado; None se nenhum


class CdiCurve:
    """Série diária do CDI (% a.d.) com acúmulo entre datas."""

    def __init__(self, rates: Mapping[date, Decimal]) -> None:
        self._dates = sorted(rates)
        self._rates = [rates[d] for d in self._dates]

    @property
    def last_date(self) -> date | None:
        return self._dates[-1] if self._dates else None

    def accumulate(self, start: date, end: date, rate_pct: Decimal = HUNDRED) -> Accrual:
        """Fator acumulado com as taxas dos dias ``start <= k < end``."""
        factor = ONE
        last: date | None = None
        i = bisect_left(self._dates, start)
        while i < len(self._dates) and self._dates[i] < end:
            factor = trunc(factor * daily_factor(self._rates[i], rate_pct), 16)
            last = self._dates[i]
            i += 1
        return Accrual(factor=factor, last_rate_date=last)


class RedemptionExceedsBalanceError(ValueError):
    def __init__(self, requested: Decimal, balance: Decimal, on: date) -> None:
        self.requested = requested
        self.balance = balance
        self.on = on
        super().__init__(
            f"resgate de {requested} maior que o saldo bruto de {balance} em {on:%d/%m/%Y}"
        )


@dataclass(slots=True)
class _Lot:
    start: date
    principal: Decimal  # principal remanescente (custo)


@dataclass(slots=True)
class FixedIncomeBook:
    """Estado de um título de renda fixa para um usuário."""

    terms: FixedIncomeTerms
    curve: CdiCurve
    lots: list[_Lot] = field(default_factory=list)
    realized_pnl: Decimal = ZERO
    income: Decimal = ZERO

    @property
    def cost_basis(self) -> Decimal:
        return sum((lot.principal for lot in self.lots), ZERO)

    def _accrual_end(self, on: date) -> date:
        # Depois do vencimento o título para de render.
        return min(on, self.terms.maturity_date)

    def _lot_value(self, lot: _Lot, on: date) -> tuple[Decimal, date | None]:
        accrual = self.curve.accumulate(lot.start, self._accrual_end(on), self.terms.rate_pct)
        return trunc(lot.principal * accrual.factor, 2), accrual.last_rate_date

    def value_at(self, on: date) -> tuple[Decimal, date | None]:
        """Valor bruto na data e o último dia de CDI aplicado (o mais antigo entre os lotes)."""
        total = ZERO
        last_dates: list[date] = []
        for lot in self.lots:
            if lot.start > on:
                continue
            value, last = self._lot_value(lot, on)
            total += value
            if last is not None:
                last_dates.append(last)
        return total, (min(last_dates) if last_dates else None)

    def apply(self, m: Movement) -> None:
        match m.type:
            case MovementType.APORTE:
                self.lots.append(_Lot(start=m.trade_date, principal=_require(m.amount)))
            case MovementType.RESGATE:
                self._redeem(_require(m.amount), m.trade_date)
            case MovementType.PROVENTO:
                self.income += _require(m.amount)
            case _:
                raise ValueError(f"{m.type} não se aplica a renda fixa")

    def _redeem(self, amount: Decimal, on: date) -> None:
        """Consome os lotes por FIFO (o mais antigo primeiro)."""
        balance, _ = self.value_at(on)
        if amount > balance + REDEMPTION_TOLERANCE:
            raise RedemptionExceedsBalanceError(amount, balance, on)
        if amount >= balance:
            # Resgate total (dentro da tolerância): fecha todos os lotes.
            self.realized_pnl += amount - self.cost_basis
            self.lots.clear()
            return
        remaining = amount
        while remaining > 0 and self.lots:
            lot = self.lots[0]
            value, _ = self._lot_value(lot, on)
            if value <= remaining:
                self.realized_pnl += value - lot.principal
                remaining -= value
                self.lots.pop(0)
            else:
                fraction = remaining / value
                consumed_principal = lot.principal * fraction
                self.realized_pnl += remaining - consumed_principal
                lot.principal -= consumed_principal
                remaining = ZERO


def _require(value: Decimal | None) -> Decimal:
    if value is None:
        raise ValueError("campo obrigatório ausente na movimentação")
    return value
