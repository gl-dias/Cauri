"""Conversão para reais das linhas importadas em outra moeda.

As cotações (PTAX de venda para dólar e stablecoins, fechamento do dia para outra cripto)
vêm de ``cauri_ledger.fx``, que o assistente também usa.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from decimal import Decimal

from cauri_core.money import q2
from cauri_importers.model import Item
from cauri_ledger import Ledger
from cauri_ledger.fx import (
    LOOKBACK_DAYS,
    PTAX_SERIES,
    STABLECOINS,
    ConversionError,
    Rate,
    RateBook,
    _brl,
    load_rates,
)

__all__ = [
    "LOOKBACK_DAYS",
    "PTAX_SERIES",
    "STABLECOINS",
    "ConversionError",
    "Converted",
    "Rate",
    "RateBook",
    "convert",
    "load",
]

_PRICE_PLACES = Decimal("1e-10")


def load(ledger: Ledger, items: Iterable[Item]) -> RateBook:
    """Busca de uma vez as cotações que as linhas vão precisar."""
    return load_rates(
        ledger,
        [
            (currency, item.trade_date)
            for item in items
            for currency in (item.currency, item.fee_asset)
            if currency
        ],
    )


@dataclass(frozen=True, slots=True)
class Converted:
    item: Item  # já em reais
    rate: Rate | None  # cotação da moeda da operação
    fee_asset: str | None  # taxa como foi paga
    fee_quantity: Decimal | None
    notes: tuple[str, ...]


def convert(item: Item, rates: RateBook) -> Converted:
    notes: list[str] = []
    rate: Rate | None = None
    unit_price, amount, fees = item.unit_price, item.amount, item.fees
    if item.currency != "BRL":
        rate = rates.rate(item.currency, item.trade_date)
        if unit_price is not None:
            unit_price = (unit_price * rate.value).quantize(_PRICE_PLACES)
        if amount is not None:
            amount = q2(amount * rate.value)
        fees = fees * rate.value
        original = item.unit_price if item.unit_price is not None else item.amount
        notes.append(
            f"Convertido de {_brl(original or Decimal(0))} {item.currency} pela "
            f"{rate.describe(item.trade_date)}."
        )
    fee_asset, fee_quantity = item.fee_asset, item.fee_quantity
    if fee_asset and fee_quantity:
        if fee_asset == "BRL":
            fees += fee_quantity
        else:
            fee_rate = rates.rate(fee_asset, item.trade_date)
            fee_brl = fee_quantity * fee_rate.value
            fees += fee_brl
            notes.append(
                f"Taxa de {_brl(fee_quantity)} {fee_asset} = R$ {_brl(q2(fee_brl))} pelo "
                f"{fee_rate.describe(item.trade_date)}, somada ao custo."
            )
    elif item.fee_paid is not None and item.fee_paid[0] != "BRL":
        fee_asset, fee_quantity = item.fee_paid
    converted = replace(
        item,
        unit_price=unit_price,
        amount=amount,
        fees=q2(fees),
        currency="BRL",
        fee_asset=None,
        fee_quantity=None,
        fee_paid=None,
    )
    return Converted(converted, rate, fee_asset, fee_quantity, tuple(notes))
