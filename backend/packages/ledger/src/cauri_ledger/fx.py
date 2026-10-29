"""Cotações para converter em reais operações em outra moeda (importação e assistente).

- Dólar e stablecoins (USDT, USDC...): PTAX de venda do dia da operação (SGS série 1).
- Outra cripto usada como moeda (par ETH/BTC, taxa em BNB): fechamento do dia em reais.

Sem cotação no dia (fim de semana, feriado, PTAX de hoje ainda não publicada), vale a
última anterior, e a linha avisa qual data foi usada.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from cauri_core.money import q2

if TYPE_CHECKING:
    from cauri_ledger.service import Ledger

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


def load_rates(ledger: Ledger, needs: Iterable[tuple[str, date]]) -> RateBook:
    """Busca de uma vez as cotações para os pares (moeda, dia) pedidos. Real não precisa."""
    needed: dict[str, list[date]] = {}
    for currency, day in needs:
        if currency and currency != "BRL":
            needed.setdefault(currency, []).append(day)
    if not needed:
        return RateBook({}, {})
    days = [d for ds in needed.values() for d in ds]
    since, until = min(days) - timedelta(days=LOOKBACK_DAYS), max(days)
    ptax = ledger.indicator(PTAX_SERIES, since, until) if needed.keys() & STABLECOINS else {}
    crypto = {c for c in needed if c not in STABLECOINS}
    return RateBook(ptax, ledger.closes(crypto, since, until) if crypto else {})


def rate_or_none(ledger: Ledger, currency: str, day: date) -> Rate | None:
    """Cotação de uma moeda num dia (ou a última antes), ou None se não houver."""
    try:
        return load_rates(ledger, [(currency, day)]).rate(currency, day)
    except ConversionError:
        return None


def brl_text(value: Decimal) -> str:
    return _brl(q2(value))
