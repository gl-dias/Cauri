"""Assistente de lançamentos: frase em português (texto ou voz) para cartão de confirmação.

Contrato::

    reply = assistant.send(ledger, user_id, "comprei 3 petrobras e vendi 2 itau",
                           extractor=AnthropicExtractor(...), today=hoje)
    assistant.answer(ledger, user_id, proposal_id, item_id, "ticker", "PETR4", today=hoje)
    assistant.confirm(ledger, user_id, proposal_id, today=hoje)

O extrator (Haiku) recebe só o que o usuário escreveu (a frase e, com cartão aberto, as
frases anteriores da conversa) e a data de hoje. Resolução de ticker e de corretora,
ambiguidade, preço sugerido, conversão de moeda e conferência no ledger são Python
determinístico.
"""

from cauri_nl_assistant.extraction import (
    Complement,
    Extraction,
    ExtractionError,
    Extractor,
    SpokenOp,
)
from cauri_nl_assistant.llm import DEFAULT_MODEL, AnthropicExtractor
from cauri_nl_assistant.resolver import Ask, NotFound, Resolved, Resolver
from cauri_nl_assistant.rules import RuleExtractor
from cauri_nl_assistant.service import (
    DEFAULT_DAILY_LIMIT,
    MAX_TEXT,
    AssistantError,
    LimitReachedError,
    ProposalClosedError,
    ProposalNotFoundError,
    Reply,
    add_opening_balance,
    answer,
    cancel,
    confirm,
    edit,
    remove,
    send,
)
from cauri_nl_assistant.transcriber import GroqTranscriber, Transcriber, TranscriptionError

__all__ = [
    "DEFAULT_DAILY_LIMIT",
    "DEFAULT_MODEL",
    "MAX_TEXT",
    "AnthropicExtractor",
    "Ask",
    "AssistantError",
    "Complement",
    "Extraction",
    "ExtractionError",
    "Extractor",
    "GroqTranscriber",
    "LimitReachedError",
    "NotFound",
    "ProposalClosedError",
    "ProposalNotFoundError",
    "Reply",
    "Resolved",
    "Resolver",
    "RuleExtractor",
    "SpokenOp",
    "Transcriber",
    "TranscriptionError",
    "add_opening_balance",
    "answer",
    "cancel",
    "confirm",
    "edit",
    "remove",
    "send",
]
