"""Importação de planilhas: envio com pré-visualização, decisões e gravação.

Fluxo: ``POST /v1/imports`` lê os arquivos e devolve a pré-visualização (nada entra no
ledger); a tela mostra erros e duplicados; ``POST /v1/imports/{id}/commit`` grava com as
decisões do usuário. Os arquivos ficam só na memória durante a requisição.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile, status

import cauri_importers as importers
from cauri_api.schemas import (
    FileProblemOut,
    ImportBatchOut,
    ImportCommitIn,
    ImportCommitOut,
    ImportDraftOut,
    ImportFileOut,
    ImportMessageOut,
    ImportPreviewOut,
    ImportRowOut,
    ImportSummaryOut,
    OpeningBalanceIn,
    OpeningSuggestionOut,
    ProfileIn,
    ProfileOut,
)
from cauri_api.session import SessionDep
from cauri_core.money import parse_br_decimal
from cauri_importers.service import MAX_FILES
from cauri_importers.table import MAX_BYTES
from cauri_ledger import ImportProfile, Ledger, StoredBatch

router = APIRouter(prefix="/v1/imports", tags=["imports"])


@router.post("", response_model=ImportPreviewOut, status_code=status.HTTP_201_CREATED)
async def upload(
    files: Annotated[list[UploadFile], File(description="Arquivos .xlsx ou .csv")],
    session: SessionDep,
) -> ImportPreviewOut:
    if len(files) > MAX_FILES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Envie no máximo {MAX_FILES} arquivos."
        )
    uploads = []
    for f in files:
        content = await f.read(MAX_BYTES + 1)  # nunca lê além do limite
        uploads.append(importers.Upload(filename=f.filename or "arquivo", content=content))
    with session.member() as conn:
        ledger = Ledger(conn)
        result = importers.preview(ledger, session.user.id, uploads)
        batch = _batch_out(ledger, result.batch) if result.batch else None
    return ImportPreviewOut(
        batch=batch,
        problems=[
            FileProblemOut(index=p.index, message=p.message, columns=list(p.columns))
            for p in result.problems
        ],
        file_indexes=list(result.file_indexes),
    )


# Perfis (antes de /{batch_id}, para "profiles" não ser lido como id de lote) -----------


@router.get("/profiles", response_model=list[ProfileOut])
def list_profiles(session: SessionDep) -> list[ProfileOut]:
    with session.member() as conn:
        found = Ledger(conn).imports.profiles(session.user.id)
    return [_profile_out(p) for p in found]


@router.post("/profiles", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def save_profile(body: ProfileIn, session: SessionDep) -> ProfileOut:
    options = body.options.model_dump(exclude_none=True)
    with session.member() as conn:
        ledger = Ledger(conn)
        if body.options.broker_id and body.options.broker_id not in ledger.brokers():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Corretora desconhecida.")
        profile_id = ledger.imports.save_profile(
            session.user.id, body.name, {str(k): v for k, v in body.mapping.items()}, options
        )
        saved = next(p for p in ledger.imports.profiles(session.user.id) if p.id == profile_id)
    return _profile_out(saved)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: UUID, session: SessionDep) -> None:
    with session.member() as conn:
        if not Ledger(conn).imports.delete_profile(session.user.id, profile_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Perfil não encontrado.")


def _profile_out(p: ImportProfile) -> ProfileOut:
    return ProfileOut(
        id=p.id,
        name=p.name,
        mapping=dict(p.mapping),
        options=dict(p.options),
        created_at=p.created_at,
        last_used_at=p.last_used_at,
    )


@router.get("", response_model=list[ImportSummaryOut])
def recent(session: SessionDep) -> list[ImportSummaryOut]:
    with session.member() as conn:
        found = Ledger(conn).imports.recent(session.user.id)
    return [
        ImportSummaryOut(
            id=b.id,
            status=b.status,
            created_at=b.created_at,
            finished_at=b.finished_at,
            labels=list(b.labels),
            imported=b.imported,
        )
        for b in found
    ]


@router.get("/{batch_id}", response_model=ImportBatchOut)
def get_batch(batch_id: UUID, session: SessionDep) -> ImportBatchOut:
    with session.member() as conn:
        ledger = Ledger(conn)
        batch = ledger.imports.batch(session.user.id, batch_id)
        if batch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Importação não encontrada.")
        return _batch_out(ledger, batch)


@router.post("/{batch_id}/commit", response_model=ImportCommitOut)
def commit(batch_id: UUID, body: ImportCommitIn, session: SessionDep) -> ImportCommitOut:
    with session.member() as conn:
        result = importers.commit(Ledger(conn), session.user.id, batch_id, body.decisions)
    refreshed = session.refresh_snapshots() if result.created else True
    return ImportCommitOut(
        created=result.created,
        already_imported=result.already_imported,
        replaced=result.replaced,
        skipped=result.skipped,
        snapshots_updated=refreshed,
    )


@router.post("/{batch_id}/opening-balances", response_model=ImportBatchOut)
def add_opening_balance(
    batch_id: UUID, body: OpeningBalanceIn, session: SessionDep
) -> ImportBatchOut:
    """Inclui no lote um saldo inicial (entra junto ao confirmar) e confere tudo de novo."""
    try:
        quantity = parse_br_decimal(body.quantity)
        unit_cost = parse_br_decimal(body.unit_cost)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Número inválido.") from exc
    with session.member() as conn:
        ledger = Ledger(conn)
        if body.broker_id not in ledger.brokers():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Corretora desconhecida.")
        batch = importers.add_opening_balance(
            ledger,
            session.user.id,
            batch_id,
            ticker=body.ticker,
            trade_date=body.trade_date,
            quantity=quantity,
            unit_cost=unit_cost,
            broker_id=body.broker_id,
        )
        return _batch_out(ledger, batch)


@router.post("/{batch_id}/discard", status_code=status.HTTP_204_NO_CONTENT)
def discard(batch_id: UUID, session: SessionDep) -> None:
    with session.member() as conn:
        importers.discard(Ledger(conn), session.user.id, batch_id)


def _batch_out(ledger: Ledger, batch: StoredBatch) -> ImportBatchOut:
    rows = [r for f in batch.files for r in f.rows]
    tickers = {r.draft["ticker"] for r in rows if r.draft and r.draft.get("ticker")}
    names = {t: a.name for t, a in ledger.assets(tickers).items()}
    brokers = ledger.brokers()

    def draft_out(draft: Mapping[str, Any] | None) -> ImportDraftOut | None:
        if draft is None:
            return None
        ticker = draft.get("ticker")
        fi = draft.get("fixed_income") or {}
        label = fi.get("label") or ticker or ""
        if ticker and ticker.startswith("TD-") and ticker in names:
            label = names[ticker]  # "Tesouro Selic 2029 (01/03/2029)" lê melhor que o código
        return ImportDraftOut(
            trade_date=draft["trade_date"],
            type=draft["type"],
            ticker=ticker,
            asset_label=label,
            broker_id=draft["broker_id"],
            broker_name=brokers.get(draft["broker_id"], draft["broker_id"]),
            quantity=draft.get("quantity"),
            unit_price=draft.get("unit_price"),
            fees=draft.get("fees"),
            amount=draft.get("amount"),
            factor=draft.get("factor"),
            income_kind=draft.get("income_kind"),
            orig_currency=draft.get("orig_currency"),
            orig_value=draft.get("orig_value"),
            fx_rate=draft.get("fx_rate"),
            fx_date=draft.get("fx_date"),
            fx_source=draft.get("fx_source"),
            fee_asset=draft.get("fee_asset"),
            fee_quantity=draft.get("fee_quantity"),
            opening_balance=bool(draft.get("opening_balance")),
        )

    return ImportBatchOut(
        id=batch.id,
        status=batch.status,
        created_at=batch.created_at,
        finished_at=batch.finished_at,
        warnings=list(batch.warnings),
        suggestions=[OpeningSuggestionOut(**s) for s in batch.suggestions],
        counts=dict(Counter(r.status for r in rows)),
        files=[
            ImportFileOut(
                id=f.id,
                label=f.label,
                adapter=f.adapter,
                counts=dict(Counter(r.status for r in f.rows)),
                rows=[
                    ImportRowOut(
                        id=r.id,
                        line_numbers=list(r.line_numbers),
                        status=r.status,
                        decision=r.decision,
                        messages=[ImportMessageOut(**m) for m in r.messages],
                        raw=dict(r.raw),
                        draft=draft_out(r.draft),
                        match_movement_ids=list(r.match_movement_ids),
                        movement_id=r.movement_id,
                    )
                    for r in f.rows
                ],
            )
            for f in batch.files
        ],
    )
