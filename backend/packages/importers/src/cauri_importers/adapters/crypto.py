"""Regras de cripto compartilhadas pelos adaptadores (Binance, template e perfis) e o
template de cripto do Cauri.

Toda negociação entre dois ativos mexe nos dois saldos. Comprar BTC com USDT é comprar
BTC e vender USDT; a taxa paga em BNB é vender um pouco de BNB. Cada perna vira uma linha
da pré-visualização, para o saldo de cada moeda bater com a exchange. Real e dólar não são
posição: pagar em BRL ou USD não gera contrapartida.

Os preços ficam na moeda da cotação (``Item.currency``); o serviço converte para reais.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from cauri_core import IncomeKind, MovementType
from cauri_importers import cells
from cauri_importers.cells import LineError
from cauri_importers.model import Item, Line, SheetRow, Ticker
from cauri_importers.privacy import normalize
from cauri_importers.table import as_text

# Moedas que não são posição no Cauri: pagar com elas não gera contrapartida.
NOT_POSITIONS = frozenset({"BRL", "USD"})
_PRICE_PLACES = Decimal("1e-10")


def _fmt(value: Decimal) -> str:
    return format(value.normalize(), "f")


def trade_lines(
    numbers: tuple[int, ...],
    raw: Mapping[str, str],
    *,
    day: date,
    buy: bool,
    base: str,
    quote: str,
    quantity: Decimal,
    price: Decimal | None,
    broker: str,
    total: Decimal | None = None,
    fee: Decimal | None = None,
    fee_asset: str | None = None,
) -> list[Line]:
    """Compra (``buy``) ou venda de ``quantity`` de ``base`` cotada em ``quote``.

    ``total`` é o valor na moeda da cotação, quando o arquivo traz (mais preciso que
    quantidade x preço). Taxa na própria base, na cotação ou num terceiro ativo.
    """
    if quantity <= 0:
        raise LineError("Quantidade deve ser maior que zero.")
    if total is None:
        if price is None:
            raise LineError("Falta o preço ou o valor total.")
        total = quantity * price
    if price is None:
        price = (total / quantity).quantize(_PRICE_PLACES)
    fee = fee if fee and fee > 0 else None
    fee_asset = (fee_asset or quote).upper() if fee else None

    main_quantity = quantity
    fees = Decimal(0)
    third_fee: tuple[str, Decimal] | None = None
    fee_paid = (fee_asset, fee) if fee is not None and fee_asset in {base, quote} else None
    quote_change = total
    if fee is not None and fee_asset == base:
        fees = fee * price
        # Na compra, a taxa sai das moedas recebidas; na venda, sai junto com as vendidas.
        main_quantity = quantity - fee if buy else quantity + fee
        if main_quantity <= 0:
            raise LineError("Taxa maior que a quantidade negociada.")
    elif fee is not None and fee_asset == quote:
        fees = fee
        quote_change = total + fee if buy else total - fee
    elif fee is not None:
        assert fee_asset is not None
        third_fee = (fee_asset, fee)

    lines = [
        Line(
            numbers=numbers,
            raw=raw,
            item=Item(
                trade_date=day,
                type=MovementType.COMPRA if buy else MovementType.VENDA,
                asset=Ticker(base),
                broker=broker,
                quantity=main_quantity,
                unit_price=price,
                fees=fees.quantize(_PRICE_PLACES),
                currency=quote,
                fee_asset=third_fee[0] if third_fee else None,
                fee_quantity=third_fee[1] if third_fee else None,
                fee_paid=fee_paid if fee_paid and fee_paid[0] is not None else None,
            ),
        )
    ]
    if quote not in NOT_POSITIONS:
        lines.append(
            _leg(
                numbers,
                raw,
                day=day,
                buy=not buy,
                coin=quote,
                quantity=quote_change,
                broker=broker,
                note=(
                    f"Contrapartida: {_fmt(quote_change)} {quote} "
                    f"{'pagos na compra' if buy else 'recebidos na venda'} de {base}."
                ),
            )
        )
    if third_fee is not None and third_fee[0] not in NOT_POSITIONS:
        lines.append(
            _leg(
                numbers,
                raw,
                day=day,
                buy=False,
                coin=third_fee[0],
                quantity=third_fee[1],
                broker=broker,
                note=f"Taxa de {_fmt(third_fee[1])} {third_fee[0]} na negociação de {base}.",
            )
        )
    return lines


def _leg(
    numbers: tuple[int, ...],
    raw: Mapping[str, str],
    *,
    day: date,
    buy: bool,
    coin: str,
    quantity: Decimal,
    broker: str,
    note: str,
) -> Line:
    """Perna em outra moeda: 1 unidade custa 1 unidade dela, e o serviço põe em reais."""
    return Line(
        numbers=numbers,
        raw=raw,
        notes=(note,),
        item=Item(
            trade_date=day,
            type=MovementType.COMPRA if buy else MovementType.VENDA,
            asset=Ticker(coin),
            broker=broker,
            quantity=quantity,
            unit_price=Decimal(1),
            currency=coin,
        ),
    )


def convert_lines(
    numbers: tuple[int, ...],
    raw: Mapping[str, str],
    *,
    day: date,
    sold: tuple[Decimal, str],
    bought: tuple[Decimal, str],
    broker: str,
) -> list[Line]:
    """Conversão (Binance Convert): vende uma moeda e compra outra pelo mesmo valor."""
    sold_qty, sold_coin = sold
    bought_qty, bought_coin = bought
    if sold_qty <= 0 or bought_qty <= 0:
        raise LineError("Conversão com quantidade zerada.")
    if bought_coin in NOT_POSITIONS:
        # Cripto vendida por real ou dólar: só a venda, cotada na moeda recebida.
        return trade_lines(
            numbers, raw, day=day, buy=False, base=sold_coin, quote=bought_coin,
            quantity=sold_qty, price=None, total=bought_qty, broker=broker,
        )  # fmt: skip
    return trade_lines(
        numbers, raw, day=day, buy=True, base=bought_coin, quote=sold_coin,
        quantity=bought_qty, price=None, total=sold_qty, broker=broker,
    )  # fmt: skip


def reward_lines(
    numbers: tuple[int, ...],
    raw: Mapping[str, str],
    *,
    day: date,
    coin: str,
    quantity: Decimal,
    broker: str,
    kind: str,
) -> list[Line]:
    """Recompensa (Earn, staking): provento pelo valor do dia e a quantidade entrando no
    saldo como compra pelo mesmo valor (reinvestida), para o saldo bater com a exchange."""
    if quantity <= 0:
        raise LineError("Recompensa com quantidade zerada.")
    income = Line(
        numbers=numbers,
        raw=raw,
        notes=(f"{kind}: entra como provento pelo valor do dia.",),
        item=Item(
            trade_date=day,
            type=MovementType.PROVENTO,
            asset=Ticker(coin),
            broker=broker,
            amount=quantity,
            income_kind=IncomeKind.RENDIMENTO,
            currency=coin,
        ),
    )
    if coin in NOT_POSITIONS:
        return [income]
    return [
        income,
        _leg(
            numbers,
            raw,
            day=day,
            buy=True,
            coin=coin,
            quantity=quantity,
            broker=broker,
            note=f"{_fmt(quantity)} {coin} recebidos entram no saldo pelo valor do dia.",
        ),
    ]


# Template de cripto ---------------------------------------------------------------

_TEMPLATE: dict[str, tuple[str, ...]] = {
    "data": ("data",),
    "tipo": ("tipo",),
    "ativo": ("ativo",),
    "quantidade": ("quantidade",),
    "preco": ("preco", "preco unitario"),
    "moeda": ("moeda do preco", "moeda"),
    "taxa": ("taxa",),
    "ativo_taxa": ("ativo da taxa",),
    "exchange": ("exchange",),
    "obs": ("obs", "observacao"),
}
BUY_WORDS = frozenset({"compra", "c", "buy", "purchase"})
SELL_WORDS = frozenset({"venda", "v", "sell", "sale"})
REWARD_WORDS = frozenset(
    {"recompensa", "reward", "rewards", "staking", "earn", "rendimento cripto", "interest"}
)
OPENING_WORDS = frozenset({"saldo inicial", "saldo_inicial", "posicao inicial", "opening"})


def opening_line(
    numbers: tuple[int, ...],
    raw: Mapping[str, str],
    *,
    day: date,
    coin: str,
    quantity: Decimal,
    unit_cost: Decimal,
    currency: str,
    broker: str,
) -> Line:
    """Saldo que já existia antes do histórico: compra marcada, com o custo médio informado.
    Não gera contrapartida (não foi pago com nada que esteja no Cauri)."""
    if quantity <= 0:
        raise LineError("Saldo inicial com quantidade zerada.")
    return Line(
        numbers=numbers,
        raw=raw,
        notes=("Saldo inicial: posição anterior ao histórico, com o custo médio informado.",),
        item=Item(
            trade_date=day,
            type=MovementType.COMPRA,
            asset=Ticker(coin),
            broker=broker,
            quantity=quantity,
            unit_price=unit_cost,
            currency=currency,
            opening_balance=True,
        ),
    )


@dataclass(frozen=True)
class CryptoTemplateAdapter:
    name: str = "planilha-cripto"
    family: str = "planilha-cripto"
    label: str = "Planilha cripto"
    title: str = "Template cripto do Cauri"
    version: int = 1
    columns: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: _TEMPLATE)
    required: frozenset[str] = frozenset({"data", "tipo", "ativo", "quantidade", "exchange"})

    def parse(self, rows: list[SheetRow]) -> list[Line]:
        lines: list[Line] = []
        for row in rows:
            raw = {k: as_text(v) for k, v in row.cells.items() if v is not None}
            numbers = (row.number,)
            try:
                lines.extend(_template_row(row, numbers, raw))
            except LineError as exc:
                lines.append(Line(numbers=numbers, raw=raw, error=str(exc)))
        return lines


def _template_row(row: SheetRow, numbers: tuple[int, ...], raw: dict[str, str]) -> list[Line]:
    c = row.cells
    kind = normalize(cells.required_text(c.get("tipo"), "o tipo"))
    day = cells.day(c.get("data"), "data")
    coin = cells.required_text(c.get("ativo"), "o ativo").upper()
    quantity = cells.number(c.get("quantidade"), "quantidade")
    broker = cells.required_text(c.get("exchange"), "a exchange")
    if kind in REWARD_WORDS:
        return reward_lines(
            numbers, raw, day=day, coin=coin, quantity=quantity, broker=broker, kind="Recompensa"
        )
    if kind in OPENING_WORDS:
        return [
            opening_line(
                numbers,
                raw,
                day=day,
                coin=coin,
                quantity=quantity,
                unit_cost=cells.number(c.get("preco"), "preco (custo médio)"),
                currency=(cells.text(c.get("moeda")) or "BRL").upper(),
                broker=broker,
            )
        ]
    if kind not in BUY_WORDS | SELL_WORDS:
        raise LineError(
            f"Tipo desconhecido: {kind}. Use compra, venda, recompensa ou saldo inicial."
        )
    currency = (cells.text(c.get("moeda")) or "BRL").upper()
    return trade_lines(
        numbers,
        raw,
        day=day,
        buy=kind in BUY_WORDS,
        base=coin,
        quote=currency,
        quantity=quantity,
        price=cells.number(c.get("preco"), "preco"),
        broker=broker,
        fee=cells.optional_number(c.get("taxa"), "taxa"),
        fee_asset=(cells.text(c.get("ativo_taxa")) or currency).upper(),
    )
