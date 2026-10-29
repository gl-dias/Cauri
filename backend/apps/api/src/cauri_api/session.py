"""Dependências da API: usuário autenticado e transação com o RLS dele.

A transação é aberta dentro do handler (``with session.member() as conn``), não numa
dependência com yield: assim o commit, onde as constraints diferidas do ledger
rodam, acontece antes da resposta, e um erro ali ainda vira resposta de erro.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from cauri_api.auth import AuthError, AuthUser, TokenVerifier
from cauri_engine.persist import last_closed_day, recalc_dirty
from cauri_storage import Conn, Pool, user_transaction

log = logging.getLogger("cauri.api")


def _verifier(request: Request) -> TokenVerifier:
    verifier: TokenVerifier = request.app.state.verifier
    return verifier


def _pool(request: Request) -> Pool:
    pool: Pool = request.app.state.pool
    return pool


def current_user(
    verifier: Annotated[TokenVerifier, Depends(_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> AuthUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Faça login para continuar.")
    try:
        return verifier.verify(authorization[7:].strip())
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada.") from exc


class Session:
    def __init__(self, user: AuthUser, pool: Pool) -> None:
        self.user = user
        self._pool = pool

    @contextmanager
    def member(self) -> Iterator[Conn]:
        """Transação como o usuário; recusa quem não está (mais) na allowlist."""
        with user_transaction(self._pool, self.user.claims) as conn:
            row = conn.execute("select app.is_member() as ok").fetchone()
            if not row or not row["ok"]:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito a convidados.")
            yield conn

    def refresh_snapshots(self) -> bool:
        """Recalcula os snapshots do usuário depois de uma escrita no ledger.

        Roda numa transação separada, depois do commit da escrita: se o recálculo
        falhar, a movimentação continua gravada, a marca em engine.dirty_ranges fica e
        o job da noite completa. Nunca derruba a resposta.
        """
        try:
            with user_transaction(self._pool, self.user.claims) as conn:
                recalc_dirty(conn, self.user.id, until=last_closed_day())
        except Exception:
            log.exception("recálculo dos snapshots falhou; o job diário completa")
            return False
        return True

    @contextmanager
    def admin(self) -> Iterator[Conn]:
        with self.member() as conn:
            row = conn.execute("select app.is_admin() as ok").fetchone()
            if not row or not row["ok"]:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Só o admin pode fazer isso.")
            yield conn


def session(
    user: Annotated[AuthUser, Depends(current_user)], pool: Annotated[Pool, Depends(_pool)]
) -> Session:
    return Session(user, pool)


SessionDep = Annotated[Session, Depends(session)]
