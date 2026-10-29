"""Perfil de importação: o mapeamento de colunas que o usuário fez para um arquivo que o
Cauri não reconhecia. Vale para bolsa e para cripto.

O perfil guarda só nomes de colunas e opções (corretora fixa, formato de data e de
número, moeda padrão). O tipo de operação é lido por um vocabulário fixo (compra, buy,
C...), então nenhum valor do arquivo precisa ser guardado.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from cauri_core import IncomeKind, MovementType
from cauri_importers import cells
from cauri_importers.adapters.crypto import (
    BUY_WORDS,
    OPENING_WORDS,
    REWARD_WORDS,
    SELL_WORDS,
    opening_line,
    reward_lines,
    trade_lines,
)
from cauri_importers.cells import LineError
from cauri_importers.model import Item, Line, SheetRow, TesouroTitle, Ticker
from cauri_importers.privacy import normalize
from cauri_importers.table import as_text
from cauri_ledger import ImportProfile

# Campos que dá para mapear, na ordem da tela. Os três primeiros são obrigatórios; a
# corretora vem de uma coluna ou da opção ``broker_id``.
FIELDS: tuple[str, ...] = (
    "data", "tipo", "ativo", "quantidade", "preco", "valor", "taxa", "ativo_taxa", "moeda",
    "corretora", "obs",
)  # fmt: skip
REQUIRED_FIELDS = frozenset({"data", "tipo", "ativo"})
DATE_FORMATS = ("dd/mm/aaaa", "aaaa-mm-dd", "mm/dd/aaaa")

_INCOME_WORDS: dict[str, IncomeKind] = {
    "dividendo": IncomeKind.DIVIDENDO,
    "dividendos": IncomeKind.DIVIDENDO,
    "dividend": IncomeKind.DIVIDENDO,
    "jcp": IncomeKind.JCP,
    "juros sobre capital proprio": IncomeKind.JCP,
    "rendimento": IncomeKind.RENDIMENTO,
    "rendimentos": IncomeKind.RENDIMENTO,
    "juros": IncomeKind.JUROS,
    "provento": IncomeKind.DIVIDENDO,
}


@dataclass(frozen=True)
class MappedAdapter:
    """Adaptador montado a partir de um perfil salvo."""

    profile: ImportProfile

    @property
    def name(self) -> str:
        return f"perfil-{str(self.profile.id)[:8]}"

    @property
    def family(self) -> str:
        return self.name

    @property
    def label(self) -> str:
        return self.profile.name

    @property
    def title(self) -> str:
        return f"Perfil {self.profile.name}"

    @property
    def version(self) -> int:
        return 1

    @property
    def columns(self) -> Mapping[str, tuple[str, ...]]:
        return {f: (normalize(col),) for f, col in self.profile.mapping.items() if f in FIELDS}

    @property
    def required(self) -> frozenset[str]:
        # Todas as colunas mapeadas precisam estar no arquivo: reconhecer é exigente.
        return frozenset(self.columns)

    def parse(self, rows: list[SheetRow]) -> list[Line]:
        options = self.profile.options
        lines: list[Line] = []
        for row in rows:
            raw = {k: as_text(v) for k, v in row.cells.items() if v is not None}
            numbers = (row.number,)
            try:
                lines.extend(_row(row, numbers, raw, options))
            except LineError as exc:
                lines.append(Line(numbers=numbers, raw=raw, error=str(exc)))
        return lines


def _row(
    row: SheetRow, numbers: tuple[int, ...], raw: dict[str, str], options: Mapping[str, Any]
) -> list[Line]:
    c = row.cells
    decimal = "." if options.get("decimal") == "." else ","
    day = cells.day(c.get("data"), "data", str(options.get("date_format") or "dd/mm/aaaa"))
    kind = normalize(cells.required_text(c.get("tipo"), "o tipo"))
    ticker_text = cells.required_text(c.get("ativo"), "o ativo")
    broker = cells.text(c.get("corretora")) or str(options.get("broker_id") or "")
    if not broker:
        raise LineError("Falta a corretora (coluna ou corretora fixa do perfil).")
    currency = (cells.text(c.get("moeda")) or str(options.get("currency") or "BRL")).upper()
    quantity = cells.optional_number(c.get("quantidade"), "quantidade", decimal)
    value = cells.optional_number(c.get("valor"), "valor", decimal)

    if kind in REWARD_WORDS:
        if quantity is None:
            raise LineError("Recompensa precisa da quantidade recebida.")
        return reward_lines(
            numbers, raw, day=day, coin=ticker_text.upper(), quantity=quantity,
            broker=broker, kind="Recompensa",
        )  # fmt: skip
    if kind in OPENING_WORDS:
        if quantity is None:
            raise LineError("Saldo inicial precisa da quantidade.")
        cost = cells.optional_number(c.get("preco"), "preco", decimal)
        if cost is None and value is not None:
            cost = value / quantity
        if cost is None:
            raise LineError("Saldo inicial precisa do custo médio (preço) ou do valor total.")
        return [
            opening_line(
                numbers, raw, day=day, coin=ticker_text.upper(), quantity=quantity,
                unit_cost=cost, currency=currency, broker=broker,
            )
        ]  # fmt: skip
    if kind in _INCOME_WORDS:
        if value is None:
            raise LineError("Provento precisa do valor.")
        return [
            Line(
                numbers=numbers,
                raw=raw,
                item=Item(
                    trade_date=day,
                    type=MovementType.PROVENTO,
                    asset=_asset(ticker_text),
                    broker=broker,
                    amount=value,
                    income_kind=_INCOME_WORDS[kind],
                    currency=currency,
                    notes=cells.text(c.get("obs")),
                ),
            )
        ]
    if kind not in BUY_WORDS | SELL_WORDS:
        raise LineError(
            f"Tipo não reconhecido: {kind}. O perfil entende compra, venda, provento e recompensa."
        )
    if quantity is None:
        raise LineError("Falta a quantidade.")
    asset = _asset(ticker_text)
    if isinstance(asset, TesouroTitle):
        price = cells.optional_number(c.get("preco"), "preco", decimal)
        if price is None and value is not None:
            price = value / quantity
        if price is None:
            raise LineError("Falta o preço ou o valor total.")
        return [
            Line(
                numbers=numbers,
                raw=raw,
                item=Item(
                    trade_date=day,
                    type=MovementType.COMPRA if kind in BUY_WORDS else MovementType.VENDA,
                    asset=asset,
                    broker=broker,
                    quantity=quantity,
                    unit_price=price,
                    fees=cells.optional_number(c.get("taxa"), "taxa", decimal) or Decimal(0),
                ),
            )
        ]
    return trade_lines(
        numbers,
        raw,
        day=day,
        buy=kind in BUY_WORDS,
        base=asset.code,
        quote=currency,
        quantity=quantity,
        price=cells.optional_number(c.get("preco"), "preco", decimal),
        total=value,
        fee=cells.optional_number(c.get("taxa"), "taxa", decimal),
        fee_asset=(cells.text(c.get("ativo_taxa")) or currency).upper(),
        broker=broker,
    )


def _asset(text: str) -> Ticker | TesouroTitle:
    if normalize(text).startswith("tesouro "):
        return TesouroTitle(text.strip())
    return Ticker(text.strip().upper())
