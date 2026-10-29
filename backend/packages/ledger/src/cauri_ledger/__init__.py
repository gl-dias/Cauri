"""Ledger: fonte única de verdade das movimentações.

Contrato com os canais de entrada::

    ledger = Ledger(conn)
    checks = ledger.check(user_id, drafts, origin=Origin.MANUAL)   # mostra ao usuário
    result = ledger.post(user_id, drafts, origin=Origin.MANUAL)    # depois de confirmar
    ledger.amend(user_id, movement_id, MovementPatch(...), reason="...")
    ledger.void(user_id, movement_id, reason="...")

Importações usam também ``source_prefix`` (duplicados entre fontes), ``replacing``
(substituir uma movimentação de outra origem na mesma transação) e ``ledger.imports``
(lotes em pré-visualização).
"""

from cauri_ledger.models import (
    CatalogAsset,
    DraftCheck,
    DuplicateCandidate,
    FixedIncomeDraft,
    Issue,
    IssueCode,
    LedgerError,
    LedgerValidationError,
    MovementChangeRejectedError,
    MovementDraft,
    MovementNotFoundError,
    MovementPatch,
    PostResult,
    Shortfall,
)
from cauri_ledger.service import Ledger
from cauri_ledger.staging import (
    BatchSummary,
    Decision,
    ImportProfile,
    ImportStore,
    RowStatus,
    StagedFile,
    StagedRow,
    StoredBatch,
    StoredFile,
    StoredRow,
)

__all__ = [
    "BatchSummary",
    "CatalogAsset",
    "Decision",
    "DraftCheck",
    "DuplicateCandidate",
    "FixedIncomeDraft",
    "ImportProfile",
    "ImportStore",
    "Issue",
    "IssueCode",
    "Ledger",
    "LedgerError",
    "LedgerValidationError",
    "MovementChangeRejectedError",
    "MovementDraft",
    "MovementNotFoundError",
    "MovementPatch",
    "PostResult",
    "RowStatus",
    "Shortfall",
    "StagedFile",
    "StagedRow",
    "StoredBatch",
    "StoredFile",
    "StoredRow",
]
