"""Escrita nos schemas que o ingest_market possui: market (curated), raw e ops."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from cauri_storage import Conn


@dataclass(frozen=True, slots=True)
class PriceRow:
    asset_id: UUID
    price_date: date
    currency: str  # BRL | USD
    close: Decimal
    source: str


def start_run(conn: Conn, job: str, trigger: str, git_sha: str | None) -> UUID:
    row = conn.execute(
        "insert into ops.job_runs (job, trigger, git_sha) values (%s, %s, %s) returning id",
        [job, trigger, git_sha],
    ).fetchone()
    assert row is not None
    run_id: UUID = row["id"]
    return run_id


def finish_run(conn: Conn, run_id: UUID, status: str, details: Mapping[str, Any]) -> None:
    conn.execute(
        "update ops.job_runs set status = %s, finished_at = now(), details = %s where id = %s",
        [status, Jsonb(dict(details)), run_id],
    )


def record_source(
    conn: Conn,
    run_id: UUID,
    source: str,
    status: str,
    *,
    requested: int,
    succeeded: int,
    failed: int,
    error_sample: str | None,
    duration_ms: int,
) -> None:
    conn.execute(
        "insert into ops.source_status"
        " (run_id, source, status, requested, succeeded, failed, error_sample, duration_ms)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s)"
        " on conflict (run_id, source) do update set status = excluded.status,"
        "   requested = excluded.requested, succeeded = excluded.succeeded,"
        "   failed = excluded.failed, error_sample = excluded.error_sample,"
        "   duration_ms = excluded.duration_ms",
        [run_id, source, status, requested, succeeded, failed, error_sample, duration_ms],
    )


def save_raw(
    conn: Conn,
    run_id: UUID,
    source: str,
    request: Mapping[str, Any],
    payload: Any,
    http_status: int | None = 200,
) -> None:
    """Guarda a resposta como chegou. Nunca inclua token em ``request``."""
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    conn.execute(
        "insert into raw.market_payloads"
        " (run_id, source, request, http_status, payload, payload_sha256)"
        " values (%s, %s, %s, %s, %s, %s)",
        [
            run_id,
            source,
            Jsonb(dict(request)),
            http_status,
            Jsonb(json.loads(text)),
            hashlib.sha256(text.encode()).hexdigest(),
        ],
    )


def upsert_prices(conn: Conn, rows: Iterable[PriceRow], run_id: UUID) -> int:
    data = [(r.asset_id, r.price_date, r.currency, r.close, r.source, run_id) for r in rows]
    if not data:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "insert into market.prices_daily"
            " (asset_id, price_date, currency, close, source, run_id)"
            " values (%s, %s, %s, %s, %s, %s)"
            " on conflict (asset_id, price_date, currency) do update"
            " set close = excluded.close, source = excluded.source, run_id = excluded.run_id,"
            "     ingested_at = now()",
            data,
        )
    return len(data)


def upsert_indicators(
    conn: Conn, series: str, unit: str, points: Iterable[tuple[date, Decimal]], run_id: UUID
) -> int:
    data = [(series, day, value, unit, run_id) for day, value in points]
    if not data:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "insert into market.indicators (series, ref_date, value, unit, run_id)"
            " values (%s, %s, %s, %s, %s)"
            " on conflict (series, ref_date) do update"
            " set value = excluded.value, unit = excluded.unit, run_id = excluded.run_id",
            data,
        )
    return len(data)


def upsert_calendar(conn: Conn, days: Iterable[tuple[date, bool]]) -> int:
    data = list(days)
    if not data:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "insert into market.calendar (day, b3_open) values (%s, %s)"
            " on conflict (day) do update set b3_open = excluded.b3_open",
            data,
        )
    return len(data)
