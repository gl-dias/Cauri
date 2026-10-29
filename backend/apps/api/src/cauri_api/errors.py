"""Erros do domínio e do banco viram respostas HTTP com mensagem em português."""

from __future__ import annotations

import logging

import psycopg
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

import cauri_importers as importers
import cauri_nl_assistant as assistant
from cauri_api.schemas import DraftCheckOut, IssueOut
from cauri_ledger import (
    LedgerValidationError,
    MovementChangeRejectedError,
    MovementNotFoundError,
)
from cauri_manual_entry import FormError
from cauri_storage import translate
from cauri_storage.errors import LAST_ADMIN, OVERSELL

log = logging.getLogger("cauri.api")


def install(app: FastAPI) -> None:
    @app.exception_handler(LedgerValidationError)
    async def _validation(_: Request, exc: LedgerValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": str(exc),
                "checks": [DraftCheckOut.of(c).model_dump(mode="json") for c in exc.checks],
            },
        )

    @app.exception_handler(MovementChangeRejectedError)
    async def _rejected(_: Request, exc: MovementChangeRejectedError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": str(exc),
                "issues": [IssueOut.of(i).model_dump(mode="json") for i in exc.issues],
            },
        )

    @app.exception_handler(MovementNotFoundError)
    async def _not_found(_: Request, exc: MovementNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})

    @app.exception_handler(importers.ImportRejectedError)
    async def _import(_: Request, exc: importers.ImportRejectedError) -> JSONResponse:
        if isinstance(exc, importers.BatchNotFoundError):
            code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, importers.BatchClosedError | importers.CommitRejectedError):
            code = status.HTTP_409_CONFLICT
        else:
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
        content: dict[str, object] = {"detail": str(exc)}
        if isinstance(exc, importers.CommitRejectedError):
            content["messages"] = exc.messages
        return JSONResponse(status_code=code, content=content)

    @app.exception_handler(assistant.AssistantError)
    async def _assistant(_: Request, exc: assistant.AssistantError) -> JSONResponse:
        if isinstance(exc, assistant.ProposalNotFoundError):
            code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, assistant.LimitReachedError):
            code = status.HTTP_429_TOO_MANY_REQUESTS
        elif isinstance(exc, assistant.ProposalClosedError):
            code = status.HTTP_409_CONFLICT
        else:
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    @app.exception_handler(assistant.ExtractionError)
    async def _extraction(_: Request, exc: assistant.ExtractionError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)})

    @app.exception_handler(assistant.TranscriptionError)
    async def _transcription(_: Request, exc: assistant.TranscriptionError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)})

    @app.exception_handler(FormError)
    async def _form(_: Request, exc: FormError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": exc.message, "field": exc.field},
        )

    @app.exception_handler(psycopg.Error)
    async def _database(_: Request, exc: psycopg.Error) -> JSONResponse:
        rule = translate(exc)
        if rule is None:
            log.exception("erro de banco não mapeado", exc_info=exc)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Erro interno. Tente de novo em instantes."},
            )
        if rule.code == "42501":
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN, content={"detail": "Sem permissão."}
            )
        conflict = {OVERSELL, LAST_ADMIN, "23505"}
        code = (
            status.HTTP_409_CONFLICT
            if rule.code in conflict
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        return JSONResponse(status_code=code, content={"detail": rule.message, "code": rule.code})
