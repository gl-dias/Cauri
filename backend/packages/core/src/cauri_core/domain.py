"""Vocabulário do domínio, espelhando os enums do banco."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class AssetClass(StrEnum):
    ACAO = "acao"
    FII = "fii"
    TESOURO = "tesouro"
    RENDA_FIXA = "renda_fixa"
    CRIPTO = "cripto"


class MovementType(StrEnum):
    COMPRA = "compra"
    VENDA = "venda"
    APORTE = "aporte"
    RESGATE = "resgate"
    PROVENTO = "provento"
    DESDOBRAMENTO = "desdobramento"
    GRUPAMENTO = "grupamento"
    BONIFICACAO = "bonificacao"


CORPORATE_EVENTS = frozenset(
    {MovementType.DESDOBRAMENTO, MovementType.GRUPAMENTO, MovementType.BONIFICACAO}
)


class IncomeKind(StrEnum):
    DIVIDENDO = "dividendo"
    JCP = "jcp"
    RENDIMENTO = "rendimento"
    JUROS = "juros"


class Origin(StrEnum):
    IMPORT = "import"
    MANUAL = "manual"
    CHAT = "chat"


class FiKind(StrEnum):
    CDB = "CDB"
    LCI = "LCI"
    LCA = "LCA"


class PriceStatus(StrEnum):
    OK = "ok"
    STALE = "stale"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class Movement:
    """Uma movimentação já gravada (ou simulada) no ledger.

    Ações, FIIs, Tesouro e cripto usam ``asset_id``; renda fixa privada (CDB, LCI,
    LCA) usa ``instrument_id``. ``seq`` desempata movimentações do mesmo dia e tipo
    pela ordem em que entraram.
    """

    id: UUID
    trade_date: date
    type: MovementType
    broker_id: str
    asset_id: UUID | None = None
    instrument_id: UUID | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    fees: Decimal = field(default=Decimal(0))
    amount: Decimal | None = None
    factor: Decimal | None = None
    income_kind: IncomeKind | None = None
    seq: int = 0

    @property
    def position_key(self) -> UUID:
        key = self.asset_id or self.instrument_id
        if key is None:  # pragma: no cover - garantido pelo banco
            raise ValueError("movimentação sem ativo nem instrumento")
        return key


@dataclass(frozen=True, slots=True)
class FixedIncomeTerms:
    """Condições de um título de renda fixa privada atrelado ao CDI."""

    id: UUID
    kind: FiKind
    issuer_name: str
    rate_pct: Decimal  # 110 = 110% do CDI
    maturity_date: date
    broker_id: str
    label: str
