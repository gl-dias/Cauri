"""Contrato do ledger com os canais de entrada (manual, importação, assistente)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from cauri_core import AssetClass, FiKind, IncomeKind, MovementType, Origin


@dataclass(frozen=True, slots=True)
class FixedIncomeDraft:
    """Condições de um CDB/LCI/LCA. Mesmas condições = mesmo título (reaproveitado)."""

    kind: FiKind
    issuer_name: str
    rate_pct: Decimal
    maturity_date: date
    label: str | None = None

    def display_label(self) -> str:
        if self.label:
            return self.label
        return (
            f"{self.kind} {self.issuer_name} {self.rate_pct.normalize():f}% CDI "
            f"{self.maturity_date:%m/%Y}"
        )


@dataclass(frozen=True, slots=True)
class MovementDraft:
    """Movimentação ainda não gravada, vinda de qualquer canal.

    ``idempotency_key`` identifica a movimentação na origem: reenviar o mesmo
    rascunho não duplica nada. Ativos negociados vão por ``ticker``; renda fixa
    privada vai por ``fixed_income`` (cria ou reaproveita o título) ou por
    ``instrument_id`` (título já existente).
    """

    idempotency_key: str
    trade_date: date
    type: MovementType
    broker_id: str
    ticker: str | None = None
    fixed_income: FixedIncomeDraft | None = None
    instrument_id: UUID | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    fees: Decimal = field(default=Decimal(0))
    amount: Decimal | None = None
    factor: Decimal | None = None
    income_kind: IncomeKind | None = None
    notes: str | None = None
    origin_label: str | None = None  # sobrepõe o rótulo do envio ("B3", "Planilha")
    # Operação em outra moeda (cripto em USDT, BTC...), já convertida para reais acima.
    # orig_value é o preço unitário (compra e venda) ou o valor (provento) na moeda original;
    # fx_rate, quantos reais vale 1 unidade da moeda em fx_date (PTAX de venda ou fechamento).
    orig_currency: str | None = None
    orig_value: Decimal | None = None
    fx_rate: Decimal | None = None
    fx_date: date | None = None
    fx_source: str | None = None  # "ptax" | "fechamento"
    # Taxa como foi paga (0,0001 BNB), já convertida e somada em ``fees``.
    fee_asset: str | None = None
    fee_quantity: Decimal | None = None
    # Compra marcada como saldo inicial (posição anterior ao histórico, custo informado).
    opening_balance: bool = False


@dataclass(frozen=True, slots=True)
class MovementPatch:
    """Campos editáveis de uma movimentação. ``None`` = não muda.

    Tipo e título de renda fixa não mudam numa edição: para isso, remova e lance de novo.
    """

    trade_date: date | None = None
    ticker: str | None = None
    broker_id: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    fees: Decimal | None = None
    amount: Decimal | None = None
    factor: Decimal | None = None
    income_kind: IncomeKind | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogAsset:
    """Ativo do cadastro de mercado, como os canais de entrada precisam ver."""

    ticker: str
    asset_class: AssetClass
    name: str
    maturity_date: date | None
    active: bool


class IssueCode(StrEnum):
    REQUIRED = "required"
    INVALID = "invalid"
    UNKNOWN_ASSET = "unknown_asset"
    UNKNOWN_BROKER = "unknown_broker"
    UNKNOWN_INSTRUMENT = "unknown_instrument"
    FUTURE_DATE = "future_date"
    OVERSELL = "oversell"
    REDEMPTION_EXCEEDS_BALANCE = "redemption_exceeds_balance"
    NOT_ALLOWED = "not_allowed"
    STALE = "stale"  # a carteira mudou entre a conferência e a gravação


@dataclass(frozen=True, slots=True)
class Issue:
    code: IssueCode
    message: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    """Movimentação já gravada, de outra origem, que parece ser a mesma operação."""

    movement_id: UUID
    origin: Origin
    origin_label: str | None
    trade_date: date


@dataclass(frozen=True, slots=True)
class Shortfall:
    """Venda maior que a posição: quanto falta de qual ativo, e em que data."""

    ticker: str
    trade_date: date
    available: Decimal
    missing: Decimal


@dataclass(frozen=True, slots=True)
class DraftCheck:
    index: int
    draft: MovementDraft
    errors: tuple[Issue, ...] = ()
    duplicates: tuple[DuplicateCandidate, ...] = ()
    already_posted: UUID | None = None  # mesma chave de idempotência já gravada
    # Venda descoberta deste rascunho: base para oferecer um saldo inicial.
    shortfall: Shortfall | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class PostResult:
    created: tuple[UUID, ...]
    already_posted: tuple[UUID, ...]


class LedgerError(Exception):
    """Base dos erros do ledger."""


class LedgerValidationError(LedgerError):
    def __init__(self, checks: list[DraftCheck]) -> None:
        self.checks = checks
        failing = [c for c in checks if not c.ok]
        first = failing[0].errors[0].message if failing else "rascunho inválido"
        super().__init__(first)


class MovementNotFoundError(LedgerError):
    def __init__(self, movement_id: UUID) -> None:
        self.movement_id = movement_id
        super().__init__("Movimentação não encontrada.")


class MovementChangeRejectedError(LedgerError):
    """Edição ou remoção que quebraria a linha do tempo (ou outra regra)."""

    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        super().__init__(issues[0].message if issues else "alteração recusada")
