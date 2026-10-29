"""Fixtures compartilhadas pelos testes que usam o banco (marcados com ``db``).

Rodam contra o Supabase local (``supabase start``). Cada teste cria usuários novos
com e-mail ``@example.test``, então não depende de limpeza: o ledger não aceita
DELETE, e é assim que tem que ser. ``supabase db reset`` zera tudo quando quiser.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest

from cauri_storage import Conn, Pool, admin_connection, make_pool, user_transaction

ADMIN_URL = os.environ.get(
    "CAURI_TEST_ADMIN_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)
API_URL = os.environ.get(
    "CAURI_TEST_API_URL", "postgresql://cauri_api:cauri_api_local@127.0.0.1:54322/postgres"
)
INGEST_URL = os.environ.get(
    "CAURI_TEST_INGEST_URL", "postgresql://cauri_ingest:cauri_ingest_local@127.0.0.1:54322/postgres"
)

TEST_BROKERS = {"corretora-teste-a": "Corretora Teste A", "corretora-teste-b": "Corretora Teste B"}
TEST_ASSETS = {
    # ticker: (classe, emissor)
    "TSTA3": ("acao", "TSTA"),
    "TSTA4": ("acao", "TSTA"),
    "TSTB4": ("acao", "TSTB"),
    "TSTF11": ("fii", "TSTF"),
    "TSTCOIN": ("cripto", None),
}


@dataclass(frozen=True)
class TestUser:
    id: uuid.UUID
    email: str

    @property
    def claims(self) -> dict[str, Any]:
        return {
            "sub": str(self.id),
            "email": self.email,
            "role": "authenticated",
            "aud": "authenticated",
        }


def _db_available() -> bool:
    try:
        with psycopg.connect(ADMIN_URL, connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session")
def admin_url() -> str:
    if not _db_available():
        pytest.skip("Supabase local fora do ar (rode `supabase start`)")
    return ADMIN_URL


@pytest.fixture(scope="session")
def reference_data(admin_url: str) -> dict[str, uuid.UUID]:
    """Corretoras e ativos de teste (idempotente). Devolve ticker -> id."""
    with admin_connection(admin_url) as conn:
        for broker_id, name in TEST_BROKERS.items():
            conn.execute(
                "insert into market.brokers (id, name, kind) values (%s, %s, 'corretora')"
                " on conflict (id) do nothing",
                [broker_id, name],
            )
        for code in {issuer for _, issuer in TEST_ASSETS.values() if issuer}:
            conn.execute(
                "insert into market.issuers (code, name) values (%s, %s)"
                " on conflict (code) do nothing",
                [code, f"Empresa {code}"],
            )
        ids: dict[str, uuid.UUID] = {}
        for ticker, (asset_class, issuer) in TEST_ASSETS.items():
            row = conn.execute(
                "insert into market.assets (ticker, class, issuer_code, name)"
                " values (%s, %s, %s, %s)"
                " on conflict (ticker) do update set ticker = excluded.ticker returning id",
                [ticker, asset_class, issuer, f"Ativo {ticker}"],
            ).fetchone()
            assert row is not None
            ids[ticker] = row["id"]
        return ids


@pytest.fixture(scope="session")
def api_url(admin_url: str) -> str:
    return API_URL


@pytest.fixture(scope="session")
def ingest_pool(admin_url: str) -> Iterator[Pool]:
    pool = make_pool(INGEST_URL)
    yield pool
    pool.close()


@pytest.fixture(scope="session")
def api_pool(admin_url: str) -> Iterator[Pool]:
    pool = make_pool(API_URL)
    yield pool
    pool.close()


@pytest.fixture
def make_user(admin_url: str):
    def _make(*, role: str = "user", member: bool = True) -> TestUser:
        user = TestUser(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:12]}@example.test")
        with admin_connection(admin_url) as conn:
            conn.execute(
                "insert into auth.users (id, instance_id, aud, role, email, raw_user_meta_data,"
                " created_at, updated_at) values (%s, '00000000-0000-0000-0000-000000000000',"
                " 'authenticated', 'authenticated', %s, '{}', now(), now())",
                [user.id, user.email],
            )
            if member:
                conn.execute(
                    "insert into app.allowlist (email, role) values (%s, %s)", [user.email, role]
                )
        return user

    return _make


@pytest.fixture
def as_user(api_pool: Pool):
    @contextmanager
    def _as(user: TestUser) -> Iterator[Conn]:
        with user_transaction(api_pool, user.claims) as conn:
            yield conn

    return _as
