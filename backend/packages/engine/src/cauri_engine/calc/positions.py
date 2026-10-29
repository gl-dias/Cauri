"""Posição e preço médio de ativos negociados (ações, FIIs, Tesouro, cripto).

Preço médio pela regra da Receita: custo médio ponderado, com as taxas da compra
somadas ao custo. Venda não altera o preço médio; ela realiza lucro ou prejuízo
contra ele. Desdobramento e grupamento mudam a quantidade sem mudar o custo total.
Bonificação soma ações novas com o custo atribuído pela empresa.

O preço médio é um só por ativo (consolidado, como na declaração). As quantidades
são acompanhadas também por corretora, para a visão por corretora.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from cauri_core import Movement, MovementType
from cauri_core.money import ZERO
from cauri_engine.calc.ordering import in_order


class OversellError(ValueError):
    """Venda maior que a posição na data."""

    def __init__(self, movement: Movement, available: Decimal) -> None:
        self.movement = movement
        self.available = available
        quantity = movement.quantity or ZERO
        self.shortfall = quantity - available
        super().__init__(
            f"venda de {quantity} maior que a posição de {available} em "
            f"{movement.trade_date:%d/%m/%Y}"
        )


@dataclass(slots=True)
class AssetBook:
    """Estado de um ativo para um usuário, atualizado movimentação a movimentação."""

    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO  # custo da posição aberta, com taxas
    realized_pnl: Decimal = ZERO
    income: Decimal = ZERO
    quantity_by_broker: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    realized_by_broker: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    income_by_broker: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))

    @property
    def avg_cost(self) -> Decimal | None:
        if self.quantity <= 0:
            return None
        return self.cost_basis / self.quantity

    def apply(self, m: Movement) -> None:
        match m.type:
            case MovementType.COMPRA:
                quantity, price = _require(m.quantity), _require(m.unit_price)
                self.cost_basis += quantity * price + m.fees
                self.quantity += quantity
                self.quantity_by_broker[m.broker_id] += quantity
            case MovementType.VENDA:
                quantity, price = _require(m.quantity), _require(m.unit_price)
                if quantity > self.quantity:
                    raise OversellError(m, self.quantity)
                cost_out = self.cost_basis * quantity / self.quantity
                proceeds = quantity * price - m.fees
                self.realized_pnl += proceeds - cost_out
                self.realized_by_broker[m.broker_id] += proceeds - cost_out
                self.quantity -= quantity
                self.quantity_by_broker[m.broker_id] -= quantity
                # Zerou: zera o custo também, sem resíduo de arredondamento.
                self.cost_basis = ZERO if self.quantity == 0 else self.cost_basis - cost_out
            case MovementType.DESDOBRAMENTO | MovementType.GRUPAMENTO:
                factor = _require(m.factor)
                self.quantity *= factor
                for broker in self.quantity_by_broker:
                    self.quantity_by_broker[broker] *= factor
            case MovementType.BONIFICACAO:
                factor, unit_cost = _require(m.factor), _require(m.unit_price)
                bonus = self.quantity * factor
                self.cost_basis += bonus * unit_cost
                self.quantity += bonus
                for broker in self.quantity_by_broker:
                    self.quantity_by_broker[broker] *= 1 + factor
            case MovementType.PROVENTO:
                amount = _require(m.amount)
                self.income += amount
                self.income_by_broker[m.broker_id] += amount
            case MovementType.APORTE | MovementType.RESGATE:
                raise ValueError("aporte e resgate são de renda fixa, não de ativo negociado")


def replay(movements: Iterable[Movement]) -> dict[UUID, AssetBook]:
    """Reprocessa movimentações de ativos negociados e devolve um livro por ativo."""
    books: dict[UUID, AssetBook] = defaultdict(AssetBook)
    for m in in_order(movements):
        if m.asset_id is not None:
            books[m.asset_id].apply(m)
    return dict(books)


@dataclass(frozen=True, slots=True)
class Oversell:
    asset_id: UUID
    trade_date: date
    movement_id: UUID
    available: Decimal
    shortfall: Decimal


def find_oversell(movements: Iterable[Movement]) -> Oversell | None:
    """Primeira venda descoberta na linha do tempo, se houver."""
    try:
        replay(movements)
    except OversellError as exc:
        asset_id = exc.movement.asset_id
        assert asset_id is not None
        return Oversell(
            asset_id=asset_id,
            trade_date=exc.movement.trade_date,
            movement_id=exc.movement.id,
            available=exc.available,
            shortfall=exc.shortfall,
        )
    return None


def _require(value: Decimal | None) -> Decimal:
    if value is None:
        raise ValueError("campo obrigatório ausente na movimentação")
    return value
