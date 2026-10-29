"""Erros do domínio e do banco viram respostas HTTP com mensagem em português."""

from __future__ import annotations

import logging

import psycopg
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

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
