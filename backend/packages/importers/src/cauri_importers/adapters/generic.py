"""Template genérico do Cauri: uma linha por movimentação, colunas em português.

Serve para qualquer corretora, banco ou exchange que a B3 não cubra, e para quem
prefere manter a própria planilha. O template e um exemplo ficam em
``reference/import-template/``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from cauri_core import FiKind, IncomeKind, MovementType
from cauri_importers import cells
from cauri_importers.cells import LineError
from cauri_importers.model import (
    AssetSpec,
    Item,
    Line,
    PrivateFixedIncome,
    SheetRow,
    TesouroTitle,
    Ticker,
)
from cauri_importers.privacy import normalize
from cauri_importers.table import as_text
from cauri_ledger import FixedIncomeDraft

_COLUMNS: dict[str, tuple[str, ...]] = {
    "data": ("data", "data da operacao"),
    "tipo": ("tipo", "operacao"),
    "ativo": ("ativo", "ticker", "titulo"),
    "classe": ("classe",),
    "quantidade": ("quantidade", "qtd", "qtde"),
    "preco": ("preco", "preco unitario"),
    "fator": ("fator",),
    "taxas": ("taxas", "custos"),
    "valor": ("valor", "valor total"),
    "corretora": ("corretora", "instituicao"),
    "pct_cdi": ("pct_cdi", "% cdi", "% do cdi"),
    "vencimento": ("vencimento",),
    "emissor": ("emissor",),
    "tipo_provento": ("tipo_provento", "tipo de provento"),
    "obs": ("obs", "observacao", "observacoes"),
}

_TYPES = {t.value: t for t in MovementType}
# Posição que já existia antes do histórico: entra como compra marcada, com o custo médio.
OPENING_WORDS = frozenset({"saldo_inicial", "saldo inicial", "posicao inicial", "opening"})
_CLASSES = {
    "acao": "acao",
    "acoes": "acao",
    "fii": "fii",
    "fiis": "fii",
    "etf": "etf",
    "etfs": "etf",
    "tesouro": "tesouro",
}
_CLASSES |= {"renda_fixa": "renda_fixa", "renda fixa": "renda_fixa", "cripto": "cripto"}
_INCOME = {k.value: k for k in IncomeKind}
_DEFAULT_INCOME = {
    "acao": IncomeKind.DIVIDENDO,
    "fii": IncomeKind.RENDIMENTO,
    "etf": IncomeKind.RENDIMENTO,
    "tesouro": IncomeKind.JUROS,
    "renda_fixa": IncomeKind.JUROS,
}


@dataclass(frozen=True)
class GenericAdapter:
    name: str = "planilha"
    family: str = "planilha"
    label: str = "Planilha"
    title: str = "Template do Cauri"
    version: int = 1
    columns: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: _COLUMNS)
    required: frozenset[str] = frozenset({"data", "tipo", "ativo", "classe", "corretora"})

    def parse(self, rows: list[SheetRow]) -> list[Line]:
        lines: list[Line] = []
        for row in rows:
            raw = {k: as_text(v) for k, v in row.cells.items() if v is not None}
            try:
                lines.append(Line(numbers=(row.number,), raw=raw, item=_item(row)))
            except LineError as exc:
                lines.append(Line(numbers=(row.number,), raw=raw, error=str(exc)))
        return lines


def _item(row: SheetRow) -> Item:
    c = row.cells
    type_text = normalize(cells.required_text(c.get("tipo"), "o tipo"))
    opening = type_text in OPENING_WORDS
    movement_type = MovementType.COMPRA if opening else _TYPES.get(type_text)
    if movement_type is None:
        raise LineError(
            f"Tipo desconhecido: {type_text}. Use: {', '.join(_TYPES)} ou saldo_inicial."
        )
    class_text = normalize(cells.required_text(c.get("classe"), "a classe"))
    asset_class = _CLASSES.get(class_text)
    if asset_class is None:
        raise LineError(
            f"Classe desconhecida: {class_text}. Use: acao, fii, etf, tesouro, renda_fixa, cripto."
        )

    income_kind: IncomeKind | None = None
    if movement_type is MovementType.PROVENTO:
        kind_text = cells.text(c.get("tipo_provento"))
        if kind_text:
            income_kind = _INCOME.get(normalize(kind_text))
            if income_kind is None:
                raise LineError(
                    f"Tipo de provento desconhecido: {kind_text}. Use: {', '.join(_INCOME)}."
                )
        else:
            income_kind = _DEFAULT_INCOME.get(asset_class)
            if income_kind is None:
                raise LineError("Informe o tipo_provento.")

    return Item(
        trade_date=cells.day(c.get("data"), "data"),
        type=movement_type,
        asset=_asset(row, asset_class),
        broker=cells.required_text(c.get("corretora"), "a corretora"),
        quantity=cells.optional_number(c.get("quantidade"), "quantidade"),
        unit_price=cells.optional_number(c.get("preco"), "preco"),
        fees=cells.optional_number(c.get("taxas"), "taxas") or Decimal(0),
        amount=cells.optional_number(c.get("valor"), "valor"),
        factor=cells.optional_number(c.get("fator"), "fator"),
        income_kind=income_kind,
        notes=cells.text(c.get("obs")),
        opening_balance=opening,
    )


def _asset(row: SheetRow, asset_class: str) -> AssetSpec:
    c = row.cells
    name = cells.required_text(c.get("ativo"), "o ativo")
    if asset_class == "renda_fixa":
        kind_text = name.split()[0].upper()
        if kind_text not in FiKind.__members__:
            raise LineError("Na renda fixa, o ativo começa com CDB, LCI ou LCA.")
        return PrivateFixedIncome(
            FixedIncomeDraft(
                kind=FiKind(kind_text),
                issuer_name=cells.required_text(c.get("emissor"), "o emissor"),
                rate_pct=cells.number(c.get("pct_cdi"), "pct_cdi"),
                maturity_date=cells.day(c.get("vencimento"), "vencimento"),
                label=name,
            )
        )
    if asset_class == "tesouro" and not name.upper().startswith("TD-"):
        return TesouroTitle(name)
    return Ticker(name.upper())
