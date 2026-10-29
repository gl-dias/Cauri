"""O que os adaptadores devolvem: uma linha interpretada por linha (ou grupo de linhas)
do arquivo, ainda sem consultar o banco.

O ativo e a corretora chegam como o arquivo escreveu; quem resolve para ticker e para
o id da corretora é o serviço, com o cadastro do ledger.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

from cauri_core import IncomeKind, MovementType
from cauri_ledger import FixedIncomeDraft

# Célula já convertida: texto, número (sempre Decimal, nunca float), data (ou data e hora,
# que é subclasse de date) ou vazia.
Cell = str | Decimal | date | None


@dataclass(frozen=True, slots=True)
class Ticker:
    code: str


@dataclass(frozen=True, slots=True)
class TesouroTitle:
    """Título do Tesouro como as planilhas escrevem: "Tesouro Selic 2029"."""

    text: str


@dataclass(frozen=True, slots=True)
class PrivateFixedIncome:
    terms: FixedIncomeDraft


AssetSpec = Ticker | TesouroTitle | PrivateFixedIncome


@dataclass(frozen=True, slots=True)
class Item:
    """Uma movimentação interpretada, antes de resolver ativo e corretora."""

    trade_date: date
    type: MovementType
    asset: AssetSpec
    broker: str  # id (slug) ou nome da corretora, como veio
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    fees: Decimal = field(default=Decimal(0))
    amount: Decimal | None = None
    factor: Decimal | None = None
    income_kind: IncomeKind | None = None
    notes: str | None = None
    # Eventos da B3 trazem as ações recebidas, não o fator: o fator sai da posição na data.
    credited: Decimal | None = None
    # Moeda de unit_price, amount e fees ("BRL", "USD", "USDT", "BTC"...). Fora do real, o
    # serviço converte pela PTAX de venda (dólar e stablecoins) ou pelo fechamento do dia.
    currency: str = "BRL"
    # Taxa paga num ativo diferente da moeda (0,0001 BNB): convertida e somada em fees.
    fee_asset: str | None = None
    fee_quantity: Decimal | None = None
    # Taxa como foi paga, quando já está em fees pela cotação (0,0005 BTC numa compra de BTC
    # em USDT entra em fees como 0,1 USDT). Só para registro no movimento.
    fee_paid: tuple[str, Decimal] | None = None
    # Compra marcada como saldo inicial (posição anterior ao histórico, custo informado).
    opening_balance: bool = False


@dataclass(frozen=True, slots=True)
class Transfer:
    """Depósito ou saque lido do arquivo. Não mexe na posição, mas explica saldo que falta."""

    kind: str  # "deposito" | "saque"
    coin: str
    quantity: Decimal
    day: date


@dataclass(frozen=True, slots=True)
class Line:
    """Resultado de uma linha do arquivo (ou de várias, quando o adaptador agrupa)."""

    numbers: tuple[int, ...]
    raw: Mapping[str, str]
    item: Item | None = None
    ignored: str | None = None  # motivo, quando a linha não vira movimentação
    error: str | None = None
    notes: tuple[str, ...] = ()  # observações que vão junto na pré-visualização
    transfer: Transfer | None = None


@dataclass(frozen=True, slots=True)
class SheetRow:
    number: int  # linha no arquivo, contando do 1 como a planilha mostra
    cells: Mapping[str, Cell]  # só as colunas que o adaptador conhece


class Adapter(Protocol):
    """Um formato de arquivo. Detectado pelo cabeçalho; lê só as colunas que declara."""

    @property
    def name(self) -> str: ...  # "b3-movimentacao"

    @property
    def family(self) -> str: ...  # fonte nas chaves de idempotência: "b3"

    @property
    def label(self) -> str: ...  # rótulo de origem no ledger: "B3"

    @property
    def title(self) -> str: ...  # nome do formato na tela: "B3 · Movimentação"

    @property
    def version(self) -> int: ...

    @property
    def columns(self) -> Mapping[str, tuple[str, ...]]:
        """Coluna canônica -> grafias aceitas no cabeçalho (já normalizadas)."""
        ...

    @property
    def required(self) -> frozenset[str]: ...

    def parse(self, rows: list[SheetRow]) -> list[Line]: ...
