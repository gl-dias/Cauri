"""Conexões com o Postgres.

Três formas de abrir uma transação, uma por tipo de chamador:

* ``user_transaction``: requests da API. Conecta como ``cauri_api`` e assume o role
  ``authenticated`` com as claims do JWT, então o RLS vale também no backend.
* ``service_transaction``: jobs (``cauri_ingest``), sem troca de role.
* ``admin_connection``: scripts de manutenção (seed do demo, bootstrap do admin),
  com o dono do banco. Nunca usado pela API.

O pooler do Supabase em modo transação não suporta prepared statements, por isso
``prepare_threshold=None``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

type Conn = Connection[DictRow]
type Pool = ConnectionPool[Conn]


def make_pool(conninfo: str, *, min_size: int = 1, max_size: int = 5) -> Pool:
    return ConnectionPool(
        conninfo,
        min_size=min_size,
        max_size=max_size,
        kwargs={"prepare_threshold": None, "row_factory": dict_row},
        connection_class=Connection[DictRow],
        open=True,
    )


@contextmanager
def user_transaction(pool: Pool, claims: Mapping[str, Any]) -> Iterator[Conn]:
    """Transação com o role ``authenticated`` e as claims do usuário.

    Se o commit falhar (por exemplo, uma constraint diferida do ledger), a exceção
    sai daqui, no fim do ``with``.
    """
    with pool.connection() as conn, conn.transaction():
        conn.execute(
            "select set_config('role', 'authenticated', true),"
            " set_config('request.jwt.claims', %s, true)",
            [json.dumps(dict(claims))],
        )
        yield conn


@contextmanager
def service_transaction(pool: Pool) -> Iterator[Conn]:
    with pool.connection() as conn, conn.transaction():
        yield conn


@contextmanager
def admin_connection(conninfo: str) -> Iterator[Conn]:
    """Conexão avulsa com privilégio de dono (seed, bootstrap). Commit no fim do bloco."""
    with psycopg.connect(conninfo, row_factory=dict_row, prepare_threshold=None) as conn:
        yield conn
