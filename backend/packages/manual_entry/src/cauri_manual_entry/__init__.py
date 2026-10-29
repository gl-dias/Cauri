"""Lançamento manual: converte o formulário em rascunho e passa pelo ledger.

Fluxo de confirmação: ``preview`` mostra erros e duplicados prováveis; ``submit``
grava depois que o usuário confirma. Editar e remover também passam pelo ledger.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from cauri_core import Origin
from cauri_ledger import DraftCheck, Ledger, PostResult
from cauri_manual_entry.form import FormError, ManualEntryForm, ManualPatchForm, to_draft, to_patch


def preview(ledger: Ledger, user_id: UUID, forms: Sequence[ManualEntryForm]) -> list[DraftCheck]:
    return ledger.check(user_id, [to_draft(f) for f in forms], origin=Origin.MANUAL)


def submit(ledger: Ledger, user_id: UUID, forms: Sequence[ManualEntryForm]) -> PostResult:
    return ledger.post(user_id, [to_draft(f) for f in forms], origin=Origin.MANUAL)


def edit(
    ledger: Ledger, user_id: UUID, movement_id: UUID, form: ManualPatchForm, reason: str | None
) -> None:
    ledger.amend(user_id, movement_id, to_patch(form), reason)


def remove(ledger: Ledger, user_id: UUID, movement_id: UUID, reason: str) -> None:
    ledger.void(user_id, movement_id, reason)


__all__ = [
    "FormError",
    "ManualEntryForm",
    "ManualPatchForm",
    "edit",
    "preview",
    "remove",
    "submit",
    "to_draft",
    "to_patch",
]
