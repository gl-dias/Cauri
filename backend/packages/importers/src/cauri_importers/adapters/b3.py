"""Exports da Área do Investidor da B3: Negociação e Movimentação.

A B3 consolida todas as corretoras. Os dois arquivos se completam:

- **Negociação**: compras e vendas de ações e FIIs (à vista e fracionário), por corretora.
  Não traz corretagem nem emolumentos.
- **Movimentação**: proventos, eventos corporativos, Tesouro Direto e a liquidação de cada
  negociação. A liquidação ("Transferência - Liquidação") é só o reflexo de uma compra ou
  venda que já veio da Negociação, então é ignorada: nunca vira movimento duplicado.

Eventos (desdobro, grupamento, bonificação) chegam como quantidade creditada por corretora.
As linhas do mesmo evento são somadas e o fator sai da posição na véspera (ver serviço).

Só as colunas abaixo são lidas. O layout segue os exports públicos da B3; tipos de
movimentação que o Cauri não trata viram erro com explicação ou linha ignorada com o
motivo, nunca somem calados.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal

from cauri_core import IncomeKind, MovementType
from cauri_importers import cells
from cauri_importers.cells import LineError
from cauri_importers.model import AssetSpec, Item, Line, SheetRow, TesouroTitle, Ticker
from cauri_importers.privacy import normalize
from cauri_importers.table import as_text

_TICKER = re.compile(r"^[A-Z0-9]{4}\d{1,2}[A-Z]?$")
_FRACTIONAL = re.compile(r"^([A-Z0-9]{4}\d{1,2})F$")


def _raw(row: SheetRow) -> dict[str, str]:
    return {k: as_text(v) for k, v in row.cells.items() if v is not None}


# Negociação ------------------------------------------------------------------------

_NEGOCIACAO: dict[str, tuple[str, ...]] = {
    "data": ("data do negocio",),
    "tipo": ("tipo de movimentacao",),
    "mercado": ("mercado",),
    "prazo": ("prazo/vencimento",),
    "instituicao": ("instituicao",),
    "codigo": ("codigo de negociacao",),
    "quantidade": ("quantidade",),
    "preco": ("preco",),
    "valor": ("valor",),
}
_SPOT_MARKETS = {"mercado a vista", "mercado fracionario"}


@dataclass(frozen=True)
class B3NegociacaoAdapter:
    name: str = "b3-negociacao"
    family: str = "b3"
    label: str = "B3"
    title: str = "B3 · Negociação"
    version: int = 1
    columns: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: _NEGOCIACAO)
    required: frozenset[str] = frozenset(
        {"data", "tipo", "instituicao", "codigo", "quantidade", "preco"}
    )

    def parse(self, rows: list[SheetRow]) -> list[Line]:
        lines: list[Line] = []
        for row in rows:
            raw = _raw(row)
            try:
                lines.append(_negociacao(row, raw))
            except LineError as exc:
                lines.append(Line(numbers=(row.number,), raw=raw, error=str(exc)))
        return lines


def _negociacao(row: SheetRow, raw: dict[str, str]) -> Line:
    c = row.cells
    numbers = (row.number,)
    market = normalize(cells.text(c.get("mercado")) or "mercado a vista")
    if market not in _SPOT_MARKETS:
        return Line(
            numbers=numbers,
            raw=raw,
            ignored=f"{cells.text(c.get('mercado'))}: opções, termo e futuros não entram no Cauri.",
        )
    kind = normalize(cells.required_text(c.get("tipo"), "o tipo de movimentação"))
    if kind not in {"compra", "venda"}:
        raise LineError(f"Tipo de negociação desconhecido: {cells.text(c.get('tipo'))}.")
    code = cells.required_text(c.get("codigo"), "o código de negociação").upper()
    fractional = _FRACTIONAL.match(code)
    ticker = fractional.group(1) if fractional else code  # PETR4F é PETR4 no fracionário
    return Line(
        numbers=numbers,
        raw=raw,
        item=Item(
            trade_date=cells.day(c.get("data"), "Data do Negócio"),
            type=MovementType.COMPRA if kind == "compra" else MovementType.VENDA,
            asset=Ticker(ticker),
            broker=cells.required_text(c.get("instituicao"), "a instituição"),
            quantity=cells.number(c.get("quantidade"), "Quantidade"),
            unit_price=cells.number(c.get("preco"), "Preço"),
        ),
    )


# Movimentação ----------------------------------------------------------------------

_MOVIMENTACAO: dict[str, tuple[str, ...]] = {
    "entrada_saida": ("entrada/saida",),
    "data": ("data",),
    "movimentacao": ("movimentacao",),
    "produto": ("produto",),
    "instituicao": ("instituicao",),
    "quantidade": ("quantidade",),
    "preco": ("preco unitario",),
    "valor": ("valor da operacao",),
}

_INCOME: dict[str, IncomeKind] = {
    "dividendo": IncomeKind.DIVIDENDO,
    "juros sobre capital proprio": IncomeKind.JCP,
    "rendimento": IncomeKind.RENDIMENTO,
    "juros": IncomeKind.JUROS,
    "pagamento de juros": IncomeKind.JUROS,
}
_EVENTS: dict[str, MovementType] = {
    "desdobro": MovementType.DESDOBRAMENTO,
    "grupamento": MovementType.GRUPAMENTO,
    "bonificacao em ativos": MovementType.BONIFICACAO,
}
_TESOURO_TRADES = {"compra / venda", "compra/venda", "compra", "venda"}
_TESOURO_EXITS = {"vencimento", "resgate", "resgate antecipado"}

# Tipo -> motivo, para o que é reflexo de outra linha ou não muda a posição.
_IGNORED: dict[str, str] = {
    "transferencia - liquidacao": (
        "Liquidação de uma compra ou venda: a operação vem do export de Negociação."
    ),
    "transferencia": "Transferência de custódia entre corretoras: a posição total não muda.",
    "fracao em ativos": "Fração de ação de um evento: a B3 vende no leilão de frações.",
    "leilao de fracao": "Venda das frações de um evento no leilão: valor pequeno, fica de fora.",
    "direito de subscricao": "Direito de subscrição recebido: só vira posição se for exercido.",
    "direitos de subscricao - nao exercido": "Direito de subscrição não exercido.",
    "cessao de direitos": "Venda de direitos de subscrição: fica de fora.",
    "cessao de direitos - solicitada": "Venda de direitos de subscrição: fica de fora.",
    "emprestimo": "Empréstimo de ações (aluguel): a posição continua sua.",
    "cobranca de taxa semestral": "Taxa de custódia do Tesouro: o Cauri mostra valor bruto.",
    "amortizacao": "Amortização (devolução de capital) ainda não ajusta o preço médio.",
    "restituicao de capital": "Restituição de capital ainda não ajusta o preço médio.",
}
# Tipo -> instrução, para o que precisa de lançamento manual.
_MANUAL: dict[str, str] = {
    "direitos de subscricao - exercido": (
        "Subscrição exercida: lance a compra das novas cotas manualmente."
    ),
    "recibo de subscricao": "Subscrição: lance a compra das novas cotas manualmente.",
    "subscricao": "Subscrição: lance a compra das novas cotas manualmente.",
    "incorporacao": "Incorporação: lance a troca de ativos manualmente.",
    "atualizacao": (
        "Atualização de posição pela B3: confira e, se mudou a posição, lance manualmente."
    ),
}


@dataclass(frozen=True)
class B3MovimentacaoAdapter:
    name: str = "b3-movimentacao"
    family: str = "b3"
    label: str = "B3"
    title: str = "B3 · Movimentação"
    version: int = 1
    columns: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: _MOVIMENTACAO)
    required: frozenset[str] = frozenset(
        {"entrada_saida", "data", "movimentacao", "produto", "instituicao"}
    )

    def parse(self, rows: list[SheetRow]) -> list[Line]:
        lines: list[Line] = []
        for row in rows:
            raw = _raw(row)
            try:
                lines.append(_movimentacao(row, raw))
            except LineError as exc:
                lines.append(Line(numbers=(row.number,), raw=raw, error=str(exc)))
        return _merge_events(lines)


def _movimentacao(row: SheetRow, raw: dict[str, str]) -> Line:
    c = row.cells
    numbers = (row.number,)
    label = cells.required_text(c.get("movimentacao"), "a movimentação")
    kind = normalize(label)
    if kind in _IGNORED:
        return Line(numbers=numbers, raw=raw, ignored=_IGNORED[kind])
    if kind in _MANUAL:
        raise LineError(_MANUAL[kind])

    credit = normalize(cells.required_text(c.get("entrada_saida"), "Entrada/Saída"))
    is_credit = credit.startswith("credito")
    if not is_credit and not credit.startswith("debito"):
        raise LineError(f"Entrada/Saída desconhecida: {cells.text(c.get('entrada_saida'))}.")
    day = cells.day(c.get("data"), "Data")
    broker = cells.required_text(c.get("instituicao"), "a instituição")
    asset = _product(cells.required_text(c.get("produto"), "o produto"))

    if kind in _INCOME:
        if not is_credit:
            raise LineError(f"{label} como débito (estorno?): confira e lance manualmente.")
        return Line(
            numbers=numbers,
            raw=raw,
            item=Item(
                trade_date=day,
                type=MovementType.PROVENTO,
                asset=asset,
                broker=broker,
                amount=cells.number(c.get("valor"), "Valor da Operação"),
                income_kind=_INCOME[kind],
            ),
        )

    if kind in _EVENTS:
        if not isinstance(asset, Ticker):
            raise LineError(f"{label} em produto que não é ação nem FII.")
        event = _EVENTS[kind]
        unit_price = None
        notes: tuple[str, ...] = ()
        if event is MovementType.BONIFICACAO:
            # Custo atribuído por ação nova, quando a B3 informa; senão zero (avisado).
            unit_price = cells.optional_number(c.get("preco"), "Preço unitário")
            if unit_price is None:
                unit_price = Decimal(0)
                notes = (
                    "A B3 não informou o custo atribuído: entrou como zero. Edite a "
                    "bonificação se a empresa divulgou o valor.",
                )
        return Line(
            numbers=numbers,
            raw=raw,
            notes=notes,
            item=Item(
                trade_date=day,
                type=event,
                asset=asset,
                broker=broker,
                unit_price=unit_price,
                credited=cells.number(c.get("quantidade"), "Quantidade"),
            ),
        )

    if kind in _TESOURO_TRADES or kind in _TESOURO_EXITS:
        if not isinstance(asset, TesouroTitle):
            return Line(
                numbers=numbers,
                raw=raw,
                ignored="Compra ou venda de ação ou FII: a operação vem do export de Negociação.",
            )
        quantity = cells.number(c.get("quantidade"), "Quantidade")
        price = cells.optional_number(c.get("preco"), "Preço unitário")
        if price is None:
            value = cells.number(c.get("valor"), "Valor da Operação")
            price = (value / quantity).quantize(Decimal("1e-10"))
        selling = kind in _TESOURO_EXITS or not is_credit
        return Line(
            numbers=numbers,
            raw=raw,
            item=Item(
                trade_date=day,
                type=MovementType.VENDA if selling else MovementType.COMPRA,
                asset=asset,
                broker=broker,
                quantity=quantity,
                unit_price=price,
            ),
        )

    raise LineError(f"Tipo de movimentação da B3 ainda não reconhecido: {label}.")


def _product(text: str) -> AssetSpec:
    """ "PETR4 - PETROLEO BRASILEIRO S.A." vira PETR4; "Tesouro Selic 2029" fica como título."""
    head = text.split(" - ", 1)[0].strip().upper()
    if _TICKER.match(head):
        return Ticker(head)
    if normalize(text).startswith("tesouro "):
        return TesouroTitle(text.strip())
    raise LineError(f"Produto não suportado: {text.split(' - ', 1)[0].strip()}.")


def _merge_events(lines: list[Line]) -> list[Line]:
    """Uma linha de evento por corretora vira um evento só (o fator vale para o ativo)."""
    merged: list[Line] = []
    index: dict[tuple[object, ...], int] = {}
    for line in lines:
        item = line.item
        if item is None or item.credited is None:
            merged.append(line)
            continue
        key = (item.type, item.asset, item.trade_date)
        at = index.get(key)
        if at is None:
            index[key] = len(merged)
            merged.append(line)
            continue
        first = merged[at]
        assert first.item is not None
        assert first.item.credited is not None
        merged[at] = replace(
            first,
            numbers=(*first.numbers, *line.numbers),
            item=replace(first.item, credited=first.item.credited + item.credited),
        )
    return merged
