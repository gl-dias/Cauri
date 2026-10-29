"""Ledger: fonte única de verdade das movimentações.

Contrato com os canais de entrada::

    ledger = Ledger(conn)
    checks = ledger.check(user_id, drafts, origin=Origin.MANUAL)   # mostra ao usuário
    result = ledger.post(user_id, drafts, origin=Origin.MANUAL)    # depois de confirmar
    ledger.amend(user_id, movement_id, MovementPatch(...), reason="...")
    ledger.void(user_id, movement_id, reason="...")
"""

from cauri_ledger.models import (
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
)
from cauri_ledger.service import Ledger

__all__ = [
    "DraftCheck",
    "DuplicateCandidate",
    "FixedIncomeDraft",
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
]
