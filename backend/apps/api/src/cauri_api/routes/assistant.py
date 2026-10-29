"""Assistente: conversa, cartão de confirmação e transcrição de voz.

Fluxo: ``POST /v1/assistant/messages`` manda a frase; a resposta traz o cartão com as
operações já resolvidas e conferidas no ledger (nada gravado). O cartão recebe respostas,
edições, remoção de itens e saldo inicial; ``/confirm`` grava tudo de uma vez.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

import cauri_nl_assistant as assistant
from cauri_api.schemas import (
    AnswerIn,
    AssistantConfigOut,
    ConversationOut,
    ConversationSummaryOut,
    EditItemIn,
    MessageIn,
    MessageOut,
    OpeningBalanceIn,
    OpeningSuggestionOut,
    ProposalOut,
    SendOut,
    TranscriptionOut,
)
from cauri_api.session import SessionDep
from cauri_core.dates import today_sp
from cauri_core.money import parse_br_decimal
from cauri_ledger import Ledger, StoredProposal
from cauri_nl_assistant.transcriber import MAX_AUDIO_BYTES

router = APIRouter(prefix="/v1/assistant", tags=["assistant"])


def _extractor(request: Request) -> assistant.Extractor:
    extractor: assistant.Extractor | None = request.app.state.extractor
    if extractor is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Assistente sem chave da Anthropic configurada no servidor.",
        )
    return extractor


@router.get("/config", response_model=AssistantConfigOut)
def config(request: Request, session: SessionDep) -> AssistantConfigOut:
    extractor: assistant.Extractor | None = request.app.state.extractor
    return AssistantConfigOut(
        llm="indisponivel"
        if extractor is None
        else ("regras" if extractor.model == "regras" else "anthropic"),
        model=extractor.model if extractor else None,
        voice="groq" if request.app.state.transcriber is not None else "navegador",
    )


@router.get("/conversations", response_model=list[ConversationSummaryOut])
def conversations(session: SessionDep) -> list[ConversationSummaryOut]:
    with session.member() as conn:
        found = Ledger(conn).conversations.recent(session.user.id)
    return [ConversationSummaryOut(id=c.id, title=c.title, updated_at=c.updated_at) for c in found]


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def conversation(conversation_id: UUID, session: SessionDep) -> ConversationOut:
    with session.member() as conn:
        store = Ledger(conn).conversations
        if not store.exists(session.user.id, conversation_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversa não encontrada.")
        messages = store.messages(session.user.id, conversation_id)
        proposals = {p.message_id: p for p in store.proposals_of(session.user.id, conversation_id)}
        title = next(
            (c.title for c in store.recent(session.user.id, 200) if c.id == conversation_id), ""
        )
    return ConversationOut(
        id=conversation_id,
        title=title,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                input_mode=m.input_mode,
                created_at=m.created_at,
                proposal=_proposal_out(proposals[m.id]) if m.id in proposals else None,
            )
            for m in messages
        ],
    )


@router.post("/messages", response_model=SendOut, status_code=status.HTTP_201_CREATED)
def send(body: MessageIn, request: Request, session: SessionDep) -> SendOut:
    extractor = _extractor(request)
    today = today_sp()
    with session.member() as conn:
        ledger = Ledger(conn, today=today)
        reply = assistant.send(
            ledger,
            session.user.id,
            body.text,
            extractor=extractor,
            today=today,
            conversation_id=body.conversation_id,
            input_mode=body.input_mode,
        )
        store = ledger.conversations
        messages = [
            m
            for m in store.messages(session.user.id, reply.conversation_id)
            if m.id in {reply.user_message_id, reply.assistant_message_id}
        ]
        proposal = store.proposal(session.user.id, reply.proposal_id) if reply.proposal_id else None
    return SendOut(
        conversation_id=reply.conversation_id,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                input_mode=m.input_mode,
                created_at=m.created_at,
                proposal=_proposal_out(proposal)
                if proposal is not None and m.id == reply.assistant_message_id
                else None,
            )
            for m in messages
        ],
    )


@router.post("/proposals/{proposal_id}/items/{item_id}/answer", response_model=ProposalOut)
def answer(proposal_id: UUID, item_id: str, body: AnswerIn, session: SessionDep) -> ProposalOut:
    return _act(
        session,
        lambda ledger, today: assistant.answer(
            ledger, session.user.id, proposal_id, item_id, body.field, body.value, today=today
        ),
    )


@router.patch("/proposals/{proposal_id}/items/{item_id}", response_model=ProposalOut)
def edit(proposal_id: UUID, item_id: str, body: EditItemIn, session: SessionDep) -> ProposalOut:
    changes = body.model_dump(exclude_none=True)
    for key in ("quantidade", "preco"):
        if key in changes:
            try:
                changes[key] = str(parse_br_decimal(changes[key]))
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "Número inválido."
                ) from exc
    if "data" in changes:
        changes["data"] = changes["data"].isoformat()
    return _act(
        session,
        lambda ledger, today: assistant.edit(
            ledger, session.user.id, proposal_id, item_id, changes, today=today
        ),
    )


@router.delete("/proposals/{proposal_id}/items/{item_id}", response_model=ProposalOut)
def remove(proposal_id: UUID, item_id: str, session: SessionDep) -> ProposalOut:
    return _act(
        session,
        lambda ledger, today: assistant.remove(
            ledger, session.user.id, proposal_id, item_id, today=today
        ),
    )


@router.post("/proposals/{proposal_id}/opening-balances", response_model=ProposalOut)
def opening_balance(proposal_id: UUID, body: OpeningBalanceIn, session: SessionDep) -> ProposalOut:
    try:
        quantity, unit_cost = parse_br_decimal(body.quantity), parse_br_decimal(body.unit_cost)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Número inválido.") from exc
    return _act(
        session,
        lambda ledger, today: assistant.add_opening_balance(
            ledger,
            session.user.id,
            proposal_id,
            ticker=body.ticker,
            trade_date=body.trade_date,
            quantity=quantity,
            unit_cost=unit_cost,
            broker_id=body.broker_id,
            today=today,
        ),
    )


@router.post("/proposals/{proposal_id}/confirm", response_model=ProposalOut)
def confirm(proposal_id: UUID, session: SessionDep) -> ProposalOut:
    result = _act(
        session,
        lambda ledger, today: assistant.confirm(ledger, session.user.id, proposal_id, today=today),
    )
    session.refresh_snapshots()
    return result


@router.post("/proposals/{proposal_id}/cancel", response_model=ProposalOut)
def cancel(proposal_id: UUID, session: SessionDep) -> ProposalOut:
    return _act(
        session, lambda ledger, today: assistant.cancel(ledger, session.user.id, proposal_id)
    )


@router.post("/transcribe", response_model=TranscriptionOut)
async def transcribe(
    request: Request,
    audio: Annotated[UploadFile, File(description="Áudio gravado no navegador")],
    session: SessionDep,
) -> TranscriptionOut:
    transcriber: assistant.Transcriber | None = request.app.state.transcriber
    if transcriber is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Sem transcrição no servidor: o navegador transcreve.",
        )
    with session.member():
        pass  # só membros transcrevem
    content = await audio.read(MAX_AUDIO_BYTES + 1)
    text = transcriber.transcribe(
        content, audio.filename or "fala.webm", audio.content_type or "audio/webm"
    )
    return TranscriptionOut(text=text)


def _act(session: SessionDep, action: Any) -> ProposalOut:
    today = today_sp()
    with session.member() as conn:
        result: StoredProposal = action(Ledger(conn, today=today), today)
        return _proposal_out(result)


def _proposal_out(p: StoredProposal) -> ProposalOut:
    return ProposalOut(
        id=p.id,
        message_id=p.message_id,
        status=p.status,
        items=[dict(i) for i in p.items],
        suggestions=[OpeningSuggestionOut(**s) for s in p.suggestions],
    )
