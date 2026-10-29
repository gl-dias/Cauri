"""Lançamento manual, edição e remoção de movimentações.

Fluxo de confirmação: ``/check`` devolve o que vai acontecer (erros, duplicados
prováveis, já gravados); a tela mostra ao usuário; só então ``POST /movements``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

import cauri_manual_entry as manual
from cauri_api.schemas import (
    ChecksOut,
    DraftCheckOut,
    ManualEntriesIn,
    MovementPatchIn,
    PostOut,
    VoidIn,
)
from cauri_api.session import SessionDep
from cauri_ledger import Ledger

router = APIRouter(prefix="/v1/movements", tags=["movements"])


@router.post("/check", response_model=ChecksOut)
def check_manual(body: ManualEntriesIn, session: SessionDep) -> ChecksOut:
    forms = [e.to_form() for e in body.entries]
    with session.member() as conn:
        checks = manual.preview(Ledger(conn), session.user.id, forms)
    return ChecksOut(ok=all(c.ok for c in checks), checks=[DraftCheckOut.of(c) for c in checks])


@router.post("", response_model=PostOut, status_code=status.HTTP_201_CREATED)
def post_manual(body: ManualEntriesIn, session: SessionDep) -> PostOut:
    forms = [e.to_form() for e in body.entries]
    with session.member() as conn:
        result = manual.submit(Ledger(conn), session.user.id, forms)
    refreshed = session.refresh_snapshots() if result.created else True
    return PostOut(
        created=list(result.created),
        already_posted=list(result.already_posted),
        snapshots_updated=refreshed,
    )


@router.patch("/{movement_id}", status_code=status.HTTP_204_NO_CONTENT)
def edit_movement(movement_id: UUID, body: MovementPatchIn, session: SessionDep) -> None:
    with session.member() as conn:
        manual.edit(Ledger(conn), session.user.id, movement_id, body.to_form(), body.reason)
    session.refresh_snapshots()


@router.post("/{movement_id}/void", status_code=status.HTTP_204_NO_CONTENT)
def void_movement(movement_id: UUID, body: VoidIn, session: SessionDep) -> None:
    with session.member() as conn:
        manual.remove(Ledger(conn), session.user.id, movement_id, body.reason)
    session.refresh_snapshots()
