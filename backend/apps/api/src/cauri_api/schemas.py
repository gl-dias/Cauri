"""Formato das requisições e respostas.

Números de dinheiro e quantidade trafegam como texto (``"1234.56"`` ou
``"1.234,56"``): JSON number viraria float no caminho, e float não entra no domínio.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cauri_core import FiKind, IncomeKind, MovementType, Origin
from cauri_ledger import DraftCheck, Issue
from cauri_manual_entry import ManualEntryForm, ManualPatchForm

NumberText = Field(default=None, max_length=40)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ManualEntryIn(_In):
    client_key: str = Field(min_length=8, max_length=100)
    type: MovementType
    trade_date: date
    broker_id: str = Field(min_length=1, max_length=60)
    ticker: str | None = Field(default=None, max_length=40)
    quantity: str | None = NumberText
    unit_price: str | None = NumberText
    fees: str | None = NumberText
    amount: str | None = NumberText
    factor: str | None = NumberText
    income_kind: IncomeKind | None = None
    instrument_id: UUID | None = None
    fi_kind: FiKind | None = None
    fi_issuer: str | None = Field(default=None, max_length=120)
    fi_rate_pct: str | None = NumberText
    fi_maturity: date | None = None
    fi_label: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=500)

    def to_form(self) -> ManualEntryForm:
        return ManualEntryForm(**self.model_dump())


class ManualEntriesIn(_In):
    entries: list[ManualEntryIn] = Field(min_length=1, max_length=50)


class MovementPatchIn(_In):
    trade_date: date | None = None
    ticker: str | None = Field(default=None, max_length=40)
    broker_id: str | None = Field(default=None, max_length=60)
    quantity: str | None = NumberText
    unit_price: str | None = NumberText
    fees: str | None = NumberText
    amount: str | None = NumberText
    factor: str | None = NumberText
    income_kind: IncomeKind | None = None
    notes: str | None = Field(default=None, max_length=500)
    reason: str | None = Field(default=None, max_length=300)

    def to_form(self) -> ManualPatchForm:
        data = self.model_dump(exclude={"reason"})
        return ManualPatchForm(**data)


class VoidIn(_In):
    reason: str = Field(min_length=1, max_length=300)


class IssueOut(BaseModel):
    code: str
    message: str
    field: str | None

    @classmethod
    def of(cls, issue: Issue) -> IssueOut:
        return cls(code=issue.code.value, message=issue.message, field=issue.field)


class DuplicateOut(BaseModel):
    movement_id: UUID
    origin: Origin
    origin_label: str | None
    trade_date: date


class DraftCheckOut(BaseModel):
    index: int
    ok: bool
    errors: list[IssueOut]
    duplicates: list[DuplicateOut]
    already_posted: UUID | None

    @classmethod
    def of(cls, check: DraftCheck) -> DraftCheckOut:
        return cls(
            index=check.index,
            ok=check.ok,
            errors=[IssueOut.of(i) for i in check.errors],
            duplicates=[
                DuplicateOut(
                    movement_id=d.movement_id,
                    origin=d.origin,
                    origin_label=d.origin_label,
                    trade_date=d.trade_date,
                )
                for d in check.duplicates
            ],
            already_posted=check.already_posted,
        )


class ChecksOut(BaseModel):
    ok: bool
    checks: list[DraftCheckOut]


class PostOut(BaseModel):
    created: list[UUID]
    already_posted: list[UUID]
    # False se o recálculo falhou: a movimentação está gravada e o job da noite completa.
    snapshots_updated: bool = True


class MeOut(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    role: Literal["admin", "user"]


class AllowlistEntryIn(_In):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Literal["admin", "user"] = "user"
    note: str | None = Field(default=None, max_length=200)


class AllowlistPatchIn(_In):
    role: Literal["admin", "user"] | None = None
    note: str | None = Field(default=None, max_length=200)


class AllowlistEntryOut(BaseModel):
    email: str
    role: Literal["admin", "user"]
    note: str | None
    added_at: datetime


# Importação -------------------------------------------------------------------------

ImportDecision = Literal["import", "keep_existing", "replace", "import_new"]
RowStatusOut = Literal["ok", "error", "already_imported", "possible_duplicate", "ignored"]
BatchStatusOut = Literal["preview", "committed", "discarded"]


class ImportMessageOut(BaseModel):
    level: Literal["error", "warning", "info"]
    text: str


class ImportDraftOut(BaseModel):
    """O que a linha vai virar no ledger, já resolvido (números como texto)."""

    trade_date: date
    type: MovementType
    ticker: str | None
    asset_label: str
    broker_id: str
    broker_name: str
    quantity: str | None
    unit_price: str | None
    fees: str | None
    amount: str | None
    factor: str | None
    income_kind: IncomeKind | None
    # Operação em outra moeda: valor original e a cotação usada na conversão.
    orig_currency: str | None = None
    orig_value: str | None = None
    fx_rate: str | None = None
    fx_date: date | None = None
    fx_source: Literal["ptax", "fechamento"] | None = None
    fee_asset: str | None = None
    fee_quantity: str | None = None


class ImportRowOut(BaseModel):
    id: UUID
    line_numbers: list[int]
    status: RowStatusOut
    decision: ImportDecision | None
    messages: list[ImportMessageOut]
    raw: dict[str, str]
    draft: ImportDraftOut | None
    match_movement_ids: list[UUID]
    movement_id: UUID | None


class ImportFileOut(BaseModel):
    id: UUID
    label: str
    adapter: str
    rows: list[ImportRowOut]
    counts: dict[str, int]


class ImportBatchOut(BaseModel):
    id: UUID
    status: BatchStatusOut
    created_at: datetime
    finished_at: datetime | None
    warnings: list[str]
    files: list[ImportFileOut]
    counts: dict[str, int]


class FileProblemOut(BaseModel):
    index: int
    message: str
    # Formato desconhecido: nomes das colunas do arquivo, para o mapeamento.
    columns: list[str] = []


class ImportPreviewOut(BaseModel):
    batch: ImportBatchOut | None
    problems: list[FileProblemOut]
    # Posição no envio de cada arquivo do lote, para a tela ligar ao nome que ela conhece.
    file_indexes: list[int]


class ImportSummaryOut(BaseModel):
    id: UUID
    status: BatchStatusOut
    created_at: datetime
    finished_at: datetime | None
    labels: list[str]
    imported: int


class ImportCommitIn(_In):
    decisions: dict[UUID, ImportDecision] = Field(default_factory=dict, max_length=20_000)


class ImportCommitOut(BaseModel):
    created: int
    already_imported: int
    replaced: int
    skipped: int
    snapshots_updated: bool = True


ProfileField = Literal[
    "data", "tipo", "ativo", "quantidade", "preco", "valor", "taxa", "ativo_taxa", "moeda",
    "corretora", "obs",
]  # fmt: skip
ColumnName = Annotated[str, Field(min_length=1, max_length=80)]


class ProfileOptionsIn(_In):
    broker_id: str | None = Field(default=None, max_length=60)
    decimal: Literal[",", "."] = ","
    date_format: Literal["dd/mm/aaaa", "aaaa-mm-dd", "mm/dd/aaaa"] = "dd/mm/aaaa"
    currency: str | None = Field(default=None, pattern=r"^[A-Z0-9]{2,12}$")


class ProfileIn(_In):
    name: str = Field(min_length=1, max_length=80)
    mapping: dict[ProfileField, ColumnName]
    options: ProfileOptionsIn = Field(default_factory=ProfileOptionsIn)

    @model_validator(mode="after")
    def _complete(self) -> ProfileIn:
        missing = {"data", "tipo", "ativo"} - set(self.mapping)
        if missing:
            raise ValueError(f"Associe as colunas de: {', '.join(sorted(missing))}.")
        if "corretora" not in self.mapping and not self.options.broker_id:
            raise ValueError("Escolha a coluna da corretora ou uma corretora fixa.")
        if "quantidade" not in self.mapping and "valor" not in self.mapping:
            raise ValueError("Associe a coluna de quantidade ou a de valor.")
        return self


class ProfileOut(BaseModel):
    id: UUID
    name: str
    mapping: dict[str, str]
    options: dict[str, Any]
    created_at: datetime
    last_used_at: datetime | None
