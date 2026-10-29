"""Seed do usuário demo e bootstrap do admin. Usam a conexão de dono do banco.

O usuário demo existe em auth.users (o ledger referencia), mas não está na allowlist e
tem e-mail inválido: nunca consegue logar. O anon do /demo lê os dados dele pelas
policies específicas do demo.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import groupby
from uuid import UUID

from psycopg.types.json import Jsonb

from cauri_core.dates import today_sp
from cauri_jobs.demo import DEMO_EMAIL, DEMO_NAME, DemoEntry, generate, price_lookup
from cauri_ledger import Ledger
from cauri_storage import Conn

log = logging.getLogger("cauri.jobs")


def bootstrap_admin(conn: Conn, email: str) -> None:
    conn.execute(
        "insert into app.allowlist (email, role, note) values (lower(%s), 'admin', 'bootstrap')"
        " on conflict (email) do update set role = 'admin'",
        [email],
    )


def ensure_demo_user(conn: Conn) -> UUID:
    row = conn.execute("select app.demo_user_id() as id").fetchone()
    if row and row["id"]:
        demo_id: UUID = row["id"]
        return demo_id
    demo_id = uuid.uuid4()
    conn.execute(
        "insert into auth.users (id, instance_id, aud, role, email, raw_user_meta_data,"
        " created_at, updated_at)"
        " values (%s, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated',"
        " %s, %s, now(), now())",
        [demo_id, DEMO_EMAIL, Jsonb({"display_name": DEMO_NAME})],
    )
    conn.execute(
        "insert into app.settings (key, value) values ('demo_user_id', %s)",
        [Jsonb(str(demo_id))],
    )
    conn.execute(
        "insert into app.goals (user_id, target_amount, target_date) values (%s, 150000, %s)"
        " on conflict (user_id) do nothing",
        [demo_id, date(today_sp().year + 1, 12, 31)],
    )
    return demo_id


def active_demo_movements(conn: Conn, demo_id: UUID) -> int:
    row = conn.execute(
        "select count(*) as n from ledger.movements where user_id = %s and voided_at is null",
        [demo_id],
    ).fetchone()
    return int(row["n"]) if row else 0


def reset_demo(conn: Conn, demo_id: UUID) -> int:
    """Remove (soft delete) todo o ledger do demo. A checagem de posição é no commit,
    quando tudo já foi removido, então a ordem não importa."""
    conn.execute("select set_config('cauri.change_reason', 'reset do demo', true)")
    result = conn.execute(
        "update ledger.movements set voided_at = now(), void_reason = 'reset do demo'"
        " where user_id = %s and voided_at is null",
        [demo_id],
    )
    return result.rowcount


def pick_tesouro(conn: Conn, today: date) -> tuple[str, str]:
    """Um Tesouro Selic e um Tesouro IPCA+ (sem cupom) ativos, com vencimento longo."""
    selic = conn.execute(
        "select ticker from market.assets where class = 'tesouro' and active"
        " and ticker like 'TD-SELIC-%%' and maturity_date >= %s order by maturity_date limit 1",
        [date(today.year + 2, 1, 1)],
    ).fetchone()
    ipca = conn.execute(
        "select ticker from market.assets where class = 'tesouro' and active"
        " and ticker like 'TD-IPCA-%%' and maturity_date >= %s order by maturity_date limit 1",
        [date(today.year + 8, 1, 1)],
    ).fetchone()
    if not selic or not ipca:
        raise LookupError("títulos do Tesouro não cadastrados: rode `cauri-jobs sync-assets`")
    return selic["ticker"], ipca["ticker"]


def load_closes(conn: Conn, tickers: list[str], since: date) -> dict[str, dict[date, Decimal]]:
    rows = conn.execute(
        "select a.ticker, p.price_date, p.close from market.prices_daily p"
        " join market.assets a on a.id = p.asset_id"
        " where a.ticker = any(%s) and p.currency = 'BRL' and p.price_date >= %s",
        [tickers, since],
    ).fetchall()
    closes: dict[str, dict[date, Decimal]] = defaultdict(dict)
    for r in rows:
        closes[r["ticker"]][r["price_date"]] = r["close"]
    return closes


@dataclass(frozen=True)
class SeedReport:
    demo_user_id: UUID
    created: int
    batches: int


def seed_demo(
    conn: Conn,
    demo_id: UUID,
    closes: dict[str, dict[date, Decimal]],
    *,
    today: date,
    tesouro: tuple[str, str],
) -> SeedReport:
    entries = generate(
        price_lookup(closes),
        today=today,
        tesouro_selic=tesouro[0],
        tesouro_ipca=tesouro[1],
        generation=uuid.uuid4().hex[:8],
    )
    ledger = Ledger(conn, today=today)
    created = 0
    batches = 0
    # Lotes consecutivos da mesma origem, em ordem cronológica: cada lote enxerga os
    # anteriores, então uma venda nunca é conferida antes da compra que a cobre.
    for (origin, label), group in groupby(entries, key=lambda e: (e.origin, e.origin_label)):
        batch: list[DemoEntry] = list(group)
        result = ledger.post(demo_id, [e.draft for e in batch], origin=origin, origin_label=label)
        created += len(result.created)
        batches += 1
    return SeedReport(demo_user_id=demo_id, created=created, batches=batches)
