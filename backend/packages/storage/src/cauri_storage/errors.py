"""Tradução dos erros próprios do banco (SQLSTATE CA0xx) para exceções Python."""

from __future__ import annotations

import json
from typing import Any

import psycopg

# Códigos definidos nas migrations (ledger: CA001 a CA006; app: CA007).
OVERSELL = "CA001"
IMMUTABLE_FIELD = "CA002"
DELETE_FORBIDDEN = "CA003"
INVALID_COMBINATION = "CA004"
FUTURE_DATE = "CA005"
VOIDED_EDIT = "CA006"
LAST_ADMIN = "CA007"

LEDGER_CODES = frozenset(
    {
        OVERSELL,
        IMMUTABLE_FIELD,
        DELETE_FORBIDDEN,
        INVALID_COMBINATION,
        FUTURE_DATE,
        VOIDED_EDIT,
        LAST_ADMIN,
    }
)


class DatabaseRuleError(Exception):
    """Uma regra do banco recusou a operação."""

    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail


def translate(exc: psycopg.Error) -> DatabaseRuleError | None:
    """Converte um erro do psycopg numa ``DatabaseRuleError`` se for regra conhecida."""
    code = exc.sqlstate
    if code not in LEDGER_CODES and code not in {"23505", "23514", "42501"}:
        return None
    message = exc.diag.message_primary or str(exc)
    detail: dict[str, Any] | None = None
    if exc.diag.message_detail:
        try:
            parsed = json.loads(exc.diag.message_detail)
            detail = parsed if isinstance(parsed, dict) else None
        except ValueError:
            detail = {"text": exc.diag.message_detail}
    return DatabaseRuleError(code=code or "", message=message, detail=detail)
