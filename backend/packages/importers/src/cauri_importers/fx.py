"""Conversão para reais das operações em outra moeda.

- Dólar e stablecoins (USDT, USDC...): PTAX de venda do dia da operação (SGS série 1).
- Outra cripto usada como moeda (par ETH/BTC, taxa em BNB): fechamento do dia em reais.

Sem cotação no dia (fim de semana, feriado, PTAX de hoje ainda não publicada), vale a
última anterior, e a linha avisa qual data foi usada.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from cauri_core.money import q2
from cauri_importers.model import Item
from cauri_ledger import Ledger

STABLECOINS = frozenset({"USD", "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI"})
PTAX_SERIES = "PTAX_VENDA"
LOOKBACK_DAYS = 10  # cobre o feriado mais longo (Carnaval com ponte)
_PRICE_PLACES = Decimal("1e-10")


@dataclass(frozen=True, slots=True)
class Rate:
    currency: str
    value: Decimal  # reais por 1 unidade da moeda
    on: date
    source: str  # "ptax" | "fechamento"

    def describe(self, wanted: date) -> str:
        what = "PTAX de venda" if self.source == "ptax" else f"fechamento do {self.currency}"
        text = f"{what} de {self.on:%d/%m/%Y} (R$ {_brl(self.value)})"
        if self.on != wanted:
            text += ", última antes da data da operação"
        return text


def _brl(value: Decimal) -> str:
    text = f"{value.normalize():f}"
    integer, _, frac = text.partition(".")
    return f"{integer},{frac}" if frac else integer


class ConversionError(ValueError):
    pass


class RateBook:
    def __init__(self, ptax: Mapping[date, Decimal], closes: Mapping[str, Mapping[date, Decimal]]):
        self._ptax = ptax
        self._closes = closes

    def rate(self, currency: str, day: date) -> Rate:
        if currency in STABLECOINS:
            series, source = self._ptax, "ptax"
        else:
            series, source = self._closes.get(currency, {}), "fechamento"
        for back in range(LOOKBACK_DAYS + 1):
            on = day - timedelta(days=back)
            value = series.get(on)
            if value is not None:
                return Rate(currency, value, on, source)
        if source == "ptax":
            raise ConversionError(
                f"Sem PTAX de venda até {day:%d/%m/%Y} para converter {currency}."
            )
        raise ConversionError(
            f"Sem fechamento em reais de {currency} perto de {day:%d/%m/%Y} para converter "
            "(o Cauri só tem preço das criptos do cadastro)."
        )


def load(ledger: Ledger, items: Iterable[Item]) -> RateBook:
    """Busca de uma vez as cotações que as linhas vão precisar."""
    needed: dict[str, list[date]] = {}
    for item in items:
        for currency in (item.currency, item.fee_asset):
            if currency and currency != "BRL":
                needed.setdefault(currency, []).append(item.trade_date)
    if not needed:
        return RateBook({}, {})
    days = [d for ds in needed.values() for d in ds]
    since, until = min(days) - timedelta(days=LOOKBACK_DAYS), max(days)
    ptax = ledger.indicator(PTAX_SERIES, since, until) if needed.keys() & STABLECOINS else {}
    crypto = {c for c in needed if c not in STABLECOINS}
    return RateBook(ptax, ledger.closes(crypto, since, until) if crypto else {})


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
