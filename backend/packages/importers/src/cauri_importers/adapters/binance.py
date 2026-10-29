"""Exports da Binance: trades (Spot), Convert, depósitos e saques, e o extrato de transações.

Os arquivos se completam, como Negociação e Movimentação na B3:

- **Trades (Spot)**: compras e vendas com par, preço, total e taxa. Dois layouts: o atual
  (``Pair``, ``Executed``, ``Amount``, ``Fee`` com a moeda junto) e o antigo (``Market``,
  ``Amount``, ``Total``, ``Fee Coin``).
- **Convert**: trocas diretas entre moedas.
- **Depósitos e saques**: transferências de custódia. A quantidade total não muda, então
  ficam como ignoradas com o motivo (mover a posição de corretora está no backlog).
- **Extrato de transações**: dele vêm as recompensas de Earn e staking. Compras, vendas e
  conversões que também aparecem nele são ignoradas, porque vêm dos exports de trades e de
  Convert: nunca entram duas vezes.

Horários vêm em UTC e viram o dia em Brasília. Números usam ponto decimal. Só as colunas
declaradas são lidas: ``User_ID``, endereço de carteira, TXID e observações nunca entram.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from cauri_importers import cells
from cauri_importers.adapters.crypto import NOT_POSITIONS, convert_lines, reward_lines, trade_lines
from cauri_importers.cells import LineError
from cauri_importers.model import Cell, Line, SheetRow
from cauri_importers.privacy import normalize
from cauri_importers.table import as_text

BROKER = "binance"
# Moedas de cotação dos pares, da mais longa para a mais curta (FDUSD antes de USD).
_QUOTES = (
    "FDUSD", "USDT", "USDC", "BUSD", "TUSD", "USDP", "BRL", "EUR", "TRY", "BTC", "ETH",
    "BNB", "DAI", "USD",
)  # fmt: skip


def _raw(row: SheetRow) -> dict[str, str]:
    return {k: as_text(v) for k, v in row.cells.items() if v is not None}


def _each(
    rows: list[SheetRow], build: Callable[[SheetRow, dict[str, str]], list[Line]]
) -> list[Line]:
    lines: list[Line] = []
    for row in rows:
        raw = _raw(row)
        try:
            lines.extend(build(row, raw))
        except LineError as exc:
            lines.append(Line(numbers=(row.number,), raw=raw, error=str(exc)))
    return lines


def _side(cell: Cell) -> bool:
    side = normalize(cells.required_text(cell, "o lado (BUY/SELL)"))
    if side in {"buy", "compra"}:
        return True
    if side in {"sell", "venda"}:
        return False
    raise LineError(f"Lado desconhecido: {side}.")


def split_pair(pair: str) -> tuple[str, str]:
    """ "BTCUSDT" -> ("BTC", "USDT"), pela moeda de cotação conhecida no fim do par."""
    code = pair.replace("/", "").replace("-", "").upper()
    for quote in _QUOTES:
        if code.endswith(quote) and len(code) > len(quote):
            return code[: -len(quote)], quote
    raise LineError(f"Par desconhecido: {pair}.")


# Trades (Spot), layout atual ---------------------------------------------------------

_SPOT: dict[str, tuple[str, ...]] = {
    "data": ("date(utc)", "date (utc)", "date"),
    "par": ("pair",),
    "lado": ("side",),
    "preco": ("price",),
    "executado": ("executed",),
    "total": ("amount",),
    "taxa": ("fee",),
}


@dataclass(frozen=True)
class BinanceSpotAdapter:
    name: str = "binance-trades"
    family: str = "binance"
    label: str = "Binance"
    title: str = "Binance · Trades (Spot)"
    version: int = 1
    columns: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: _SPOT)
    required: frozenset[str] = frozenset({"data", "par", "lado", "executado", "total"})

    def parse(self, rows: list[SheetRow]) -> list[Line]:
        return _each(rows, _spot)


def _spot(row: SheetRow, raw: dict[str, str]) -> list[Line]:
    c = row.cells
    quantity, base = cells.amount_and_coin(c.get("executado"), "Executed")
    total, quote = cells.amount_and_coin(c.get("total"), "Amount")
    fee, fee_asset = (
        cells.amount_and_coin(c.get("taxa"), "Fee") if c.get("taxa") is not None else (None, None)
    )
    return trade_lines(
        (row.number,),
        raw,
        day=cells.utc_day(c.get("data"), "Date(UTC)"),
        buy=_side(c.get("lado")),
        base=base,
        quote=quote,
        quantity=quantity,
        price=cells.optional_number(c.get("preco"), "Price", "."),
        total=total,
        fee=fee,
        fee_asset=fee_asset,
        broker=BROKER,
    )


# Trades (Spot), layout antigo -------------------------------------------------------

_SPOT_LEGACY: dict[str, tuple[str, ...]] = {
    "data": ("date(utc)", "date (utc)"),
    "par": ("market",),
    "lado": ("type",),
    "preco": ("price",),
    "quantidade": ("amount",),
    "total": ("total",),
    "taxa": ("fee",),
    "moeda_taxa": ("fee coin",),
}


@dataclass(frozen=True)
class BinanceSpotLegacyAdapter:
    name: str = "binance-trades-antigo"
    family: str = "binance"
    label: str = "Binance"
    title: str = "Binance · Trades (Spot, layout antigo)"
    version: int = 1
    columns: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: _SPOT_LEGACY)
    required: frozenset[str] = frozenset({"data", "par", "lado", "quantidade", "total"})

    def parse(self, rows: list[SheetRow]) -> list[Line]:
        return _each(rows, _spot_legacy)


def _spot_legacy(row: SheetRow, raw: dict[str, str]) -> list[Line]:
    c = row.cells
    base, quote = split_pair(cells.required_text(c.get("par"), "Market"))
    fee = cells.optional_number(c.get("taxa"), "Fee", ".")
    return trade_lines(
        (row.number,),
        raw,
        day=cells.utc_day(c.get("data"), "Date(UTC)"),
        buy=_side(c.get("lado")),
        base=base,
        quote=quote,
        quantity=cells.number(c.get("quantidade"), "Amount", "."),
        price=cells.optional_number(c.get("preco"), "Price", "."),
        total=cells.number(c.get("total"), "Total", "."),
        fee=fee,
        fee_asset=cells.text(c.get("moeda_taxa")),
        broker=BROKER,
    )


# Convert ---------------------------------------------------------------------------

_CONVERT: dict[str, tuple[str, ...]] = {
    "data": ("date", "date(utc)", "date (utc)"),
    "vendido": ("sell",),
    "comprado": ("buy",),
    "status": ("status",),
}


@dataclass(frozen=True)
class BinanceConvertAdapter:
    name: str = "binance-convert"
    family: str = "binance"
    label: str = "Binance"
    title: str = "Binance · Convert"
    version: int = 1
    columns: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: _CONVERT)
    required: frozenset[str] = frozenset({"data", "vendido", "comprado", "status"})

    def parse(self, rows: list[SheetRow]) -> list[Line]:
        return _each(rows, _convert)


def _convert(row: SheetRow, raw: dict[str, str]) -> list[Line]:
    c = row.cells
    status = normalize(cells.text(c.get("status")) or "")
    if status not in {"successful", "success", "sucesso", "concluido", "concluida"}:
        return [Line(numbers=(row.number,), raw=raw, ignored="Conversão não concluída.")]
    return convert_lines(
        (row.number,),
        raw,
        day=cells.utc_day(c.get("data"), "Date"),
        sold=cells.amount_and_coin(c.get("vendido"), "Sell"),
        bought=cells.amount_and_coin(c.get("comprado"), "Buy"),
        broker=BROKER,
    )


# Depósitos e saques ----------------------------------------------------------------

_TRANSFERS: dict[str, tuple[str, ...]] = {
    "data": ("date(utc)", "date (utc)", "date"),
    "moeda": ("coin",),
    "rede": ("network",),
    "quantidade": ("amount",),
    "taxa": ("fee", "transaction fee"),
    "status": ("status",),
}


@dataclass(frozen=True)
class BinanceTransfersAdapter:
    name: str = "binance-transferencias"
    family: str = "binance"
    label: str = "Binance"
    title: str = "Binance · Depósitos e saques"
    version: int = 1
    columns: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: _TRANSFERS)
    required: frozenset[str] = frozenset({"data", "moeda", "rede", "quantidade"})

    def parse(self, rows: list[SheetRow]) -> list[Line]:
        return _each(rows, _transfer)


def _transfer(row: SheetRow, raw: dict[str, str]) -> list[Line]:
    c = row.cells
    coin = cells.required_text(c.get("moeda"), "Coin").upper()
    # O histórico de saques tem a coluna de taxa; o de depósitos, não.
    kind = "Saque" if "taxa" in c else "Depósito"
    return [Line(numbers=(row.number,), raw=raw, ignored=transfer_reason(kind, coin))]


def transfer_reason(kind: str, coin: str) -> str:
    if coin in NOT_POSITIONS:
        return f"{kind} em {coin}: dinheiro em conta não é posição no Cauri."
    return (
        f"{kind} de {coin}: transferência de custódia, a quantidade total não muda "
        "(mover a posição de corretora está no backlog)."
    )


# Extrato de transações --------------------------------------------------------------

_STATEMENT: dict[str, tuple[str, ...]] = {
    "data": ("utc_time", "utc time", "time"),
    "conta": ("account",),
    "operacao": ("operation",),
    "moeda": ("coin",),
    "variacao": ("change",),
}

_FROM_TRADES = "Compra, venda ou taxa de negociação: vem do export de trades (Spot) ou de Convert."
_STATEMENT_IGNORED: dict[str, str] = {
    **{
        op: _FROM_TRADES
        for op in (
            "buy",
            "sell",
            "fee",
            "transaction buy",
            "transaction spend",
            "transaction fee",
            "transaction revenue",
            "transaction sold",
            "transaction related",
            "binance convert",
            "large otc trading",
        )
    },
    "small assets exchange bnb": (
        "Conversão de saldos pequenos em BNB: valores mínimos, fica de fora."
    ),
    "fiat deposit": "Depósito em reais: dinheiro em conta não é posição no Cauri.",
    "fiat withdraw": "Saque em reais: dinheiro em conta não é posição no Cauri.",
}
_INTERNAL = ("subscription", "redemption", "transfer", "purchase")
_MANUAL: dict[str, str] = {
    "p2p trading": "P2P: lance manualmente a compra ou venda (não vem no export de trades).",
    "auto-invest transaction": "Auto-Invest: lance manualmente as compras do plano.",
}


@dataclass(frozen=True)
class BinanceStatementAdapter:
    name: str = "binance-extrato"
    family: str = "binance"
    label: str = "Binance"
    title: str = "Binance · Extrato de transações"
    version: int = 1
    columns: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: _STATEMENT)
    required: frozenset[str] = frozenset({"data", "operacao", "moeda", "variacao"})

    def parse(self, rows: list[SheetRow]) -> list[Line]:
        return _each(rows, _statement)


def is_reward(operation: str) -> bool:
    """Recompensas de Earn, staking, Launchpool e airdrops."""
    return (
        "interest" in operation
        or "reward" in operation
        or "airdrop" in operation
        or operation in {"distribution", "staking rewards"}
    )


def _statement(row: SheetRow, raw: dict[str, str]) -> list[Line]:
    c = row.cells
    label = cells.required_text(c.get("operacao"), "Operation")
    operation = normalize(label)
    numbers = (row.number,)
    if operation in _STATEMENT_IGNORED:
        return [Line(numbers=numbers, raw=raw, ignored=_STATEMENT_IGNORED[operation])]
    if operation in {"deposit", "withdraw"}:
        kind = "Depósito" if operation == "deposit" else "Saque"
        coin = cells.required_text(c.get("moeda"), "Coin").upper()
        return [Line(numbers=numbers, raw=raw, ignored=transfer_reason(kind, coin))]
    if operation in _MANUAL:
        raise LineError(_MANUAL[operation])
    if is_reward(operation):
        change = cells.number(c.get("variacao"), "Change", ".")
        if change <= 0:
            raise LineError(f"{label} com valor negativo: confira e lance manualmente.")
        return reward_lines(
            numbers,
            raw,
            day=cells.utc_day(c.get("data"), "UTC_Time"),
            coin=cells.required_text(c.get("moeda"), "Coin").upper(),
            quantity=change,
            broker=BROKER,
            kind=label,
        )
    if any(word in operation for word in _INTERNAL):
        return [
            Line(
                numbers=numbers,
                raw=raw,
                ignored="Movimento entre carteiras da própria Binance: a posição não muda.",
            )
        ]
    raise LineError(f"Operação da Binance ainda não reconhecida: {label}.")
