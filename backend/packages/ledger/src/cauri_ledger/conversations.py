"""Conversas com o assistente: mensagens e propostas (os cartões de confirmação).

O conteúdo das mensagens é o que o usuário digitou ou falou e a resposta do assistente.
``llm_output`` guarda só o que o LLM extraiu da frase: o LLM nunca recebe a carteira.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from psycopg.types.json import Jsonb

from cauri_storage import Conn

ProposalStatus = Literal["pending", "confirmed", "cancelled"]


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    id: UUID
    title: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StoredMessage:
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    input_mode: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredProposal:
    id: UUID
    message_id: UUID
    status: ProposalStatus
    items: tuple[Mapping[str, Any], ...]
    suggestions: tuple[Mapping[str, Any], ...]
    created_at: datetime


class ConversationStore:
    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    def create(self, user_id: UUID, title: str) -> UUID:
        row = self._conn.execute(
            "insert into assistant.conversations (user_id, title) values (%s, %s) returning id",
            [user_id, title.strip()[:120] or "Conversa"],
        ).fetchone()
        assert row is not None
        conversation_id: UUID = row["id"]
        return conversation_id

    def exists(self, user_id: UUID, conversation_id: UUID) -> bool:
        row = self._conn.execute(
            "select 1 from assistant.conversations where user_id = %s and id = %s",
            [user_id, conversation_id],
        ).fetchone()
        return row is not None

    def recent(self, user_id: UUID, limit: int = 30) -> list[ConversationSummary]:
        rows = self._conn.execute(
            "select id, title, updated_at from assistant.conversations where user_id = %s"
            " order by updated_at desc limit %s",
            [user_id, limit],
        ).fetchall()
        return [ConversationSummary(r["id"], r["title"], r["updated_at"]) for r in rows]

    def add_message(
        self,
        user_id: UUID,
        conversation_id: UUID,
        role: Literal["user", "assistant"],
        content: str,
        *,
        input_mode: str | None = None,
        llm_model: str | None = None,
        llm_output: Mapping[str, Any] | None = None,
    ) -> UUID:
        row = self._conn.execute(
            "insert into assistant.messages"
            " (conversation_id, user_id, role, content, input_mode, llm_model, llm_output)"
            " values (%s, %s, %s, %s, %s, %s, %s) returning id",
            [
                conversation_id,
                user_id,
                role,
                content[:4000],
                input_mode,
                llm_model,
                Jsonb(dict(llm_output)) if llm_output is not None else None,
            ],
        ).fetchone()
        assert row is not None
        self._conn.execute(
            "update assistant.conversations set updated_at = now() where user_id = %s and id = %s",
            [user_id, conversation_id],
        )
        message_id: UUID = row["id"]
        return message_id

    def messages(self, user_id: UUID, conversation_id: UUID) -> list[StoredMessage]:
        rows = self._conn.execute(
            "select id, role, content, input_mode, created_at from assistant.messages"
            " where user_id = %s and conversation_id = %s order by created_at, id",
            [user_id, conversation_id],
        ).fetchall()
        return [
            StoredMessage(r["id"], r["role"], r["content"], r["input_mode"], r["created_at"])
            for r in rows
        ]

    def create_proposal(
        self,
        user_id: UUID,
        message_id: UUID,
        items: Sequence[Mapping[str, Any]],
        suggestions: Sequence[Mapping[str, Any]],
        *,
        proposal_id: UUID,
    ) -> UUID:
        row = self._conn.execute(
            "insert into assistant.proposals (id, message_id, user_id, items, suggestions)"
            " values (%s, %s, %s, %s, %s) returning id",
            [
                proposal_id,
                message_id,
                user_id,
                Jsonb([dict(i) for i in items]),
                Jsonb([dict(s) for s in suggestions]),
            ],
        ).fetchone()
        assert row is not None
        created: UUID = row["id"]
        return created

    def record_usage(
        self,
        user_id: UUID,
        *,
        provider: str,
        kind: Literal["mensagem", "transcricao"],
        model: str,
        ok: bool,
        day: date,
        input_tokens: int = 0,
        output_tokens: int = 0,
        audio_bytes: int = 0,
    ) -> None:
        """Uma chamada paga (Haiku ou Whisper), para o limite diário e para o Admin."""
        self._conn.execute(
            "insert into ops.llm_usage (user_id, day, provider, kind, model, input_tokens,"
            " output_tokens, audio_bytes, ok) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                user_id,
                day,
                provider,
                kind,
                model[:80],
                input_tokens,
                output_tokens,
                audio_bytes,
                ok,
            ],
        )

    def usage_on(self, user_id: UUID, kind: str, day: date) -> int:
        row = self._conn.execute(
            "select count(*) as n from ops.llm_usage where user_id = %s and kind = %s and day = %s",
            [user_id, kind, day],
        ).fetchone()
        return int(row["n"]) if row else 0

    def conversation_of(self, user_id: UUID, message_id: UUID) -> UUID | None:
        row = self._conn.execute(
            "select conversation_id from assistant.messages where user_id = %s and id = %s",
            [user_id, message_id],
        ).fetchone()
        return row["conversation_id"] if row else None

    def proposal(self, user_id: UUID, proposal_id: UUID) -> StoredProposal | None:
        row = self._conn.execute(
            "select id, message_id, status, items, suggestions, created_at"
            " from assistant.proposals where user_id = %s and id = %s",
            [user_id, proposal_id],
        ).fetchone()
        return _proposal(row) if row else None

    def proposals_of(self, user_id: UUID, conversation_id: UUID) -> list[StoredProposal]:
        rows = self._conn.execute(
            "select p.id, p.message_id, p.status, p.items, p.suggestions, p.created_at"
            " from assistant.proposals p join assistant.messages m on m.id = p.message_id"
            " where p.user_id = %s and m.conversation_id = %s order by p.created_at",
            [user_id, conversation_id],
        ).fetchall()
        return [_proposal(r) for r in rows]

    def open_proposal(self, user_id: UUID, conversation_id: UUID) -> StoredProposal | None:
        """O cartão pendente mais recente da conversa, se houver."""
        pending = [p for p in self.proposals_of(user_id, conversation_id) if p.status == "pending"]
        return pending[-1] if pending else None

    def recent_user_texts(self, user_id: UUID, conversation_id: UUID, limit: int) -> list[str]:
        """As últimas frases do usuário na conversa, da mais antiga para a mais nova."""
        rows = self._conn.execute(
            "select content from assistant.messages"
            " where user_id = %s and conversation_id = %s and role = 'user'"
            " order by created_at desc, id desc limit %s",
            [user_id, conversation_id, limit],
        ).fetchall()
        return [r["content"] for r in reversed(rows)]

    def move_proposal(self, user_id: UUID, proposal_id: UUID, message_id: UUID) -> None:
        """Leva o cartão para outra mensagem (a resposta mais recente da conversa)."""
        self._conn.execute(
            "update assistant.proposals set message_id = %s where user_id = %s and id = %s",
            [message_id, user_id, proposal_id],
        )

    def save_proposal(
        self,
        user_id: UUID,
        proposal_id: UUID,
        items: Sequence[Mapping[str, Any]],
        suggestions: Sequence[Mapping[str, Any]],
        status: ProposalStatus = "pending",
    ) -> None:
        self._conn.execute(
            "update assistant.proposals set items = %s, suggestions = %s, status = %s,"
            "  finished_at = case when %s = 'pending' then null else now() end"
            " where user_id = %s and id = %s",
            [
                Jsonb([dict(i) for i in items]),
                Jsonb([dict(s) for s in suggestions]),
                status,
                status,
                user_id,
                proposal_id,
            ],
        )


def _proposal(row: Mapping[str, Any]) -> StoredProposal:
    return StoredProposal(
        id=row["id"],
        message_id=row["message_id"],
        status=row["status"],
        items=tuple(row["items"]),
        suggestions=tuple(row["suggestions"]),
        created_at=row["created_at"],
    )
