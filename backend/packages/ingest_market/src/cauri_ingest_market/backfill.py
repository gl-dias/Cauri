"""Histórico de preços e indicadores: carteiras reais e o seed do demo.

Fontes por classe (a brapi fica só para o fechamento diário, porque o plano gratuito
tem 3 meses de histórico):
  * ações e FIIs: COTAHIST da B3;
  * Tesouro: CSV do Tesouro Transparente;
  * cripto: CoinGecko (BRL e USD; o plano Demo cobre até 365 dias);
  * CDI, Selic meta, Selic efetiva e IPCA: SGS do Banco Central.

Cada fonte roda na sua transação e registra o status em ops.source_status: uma fonte
fora do ar não derruba as outras, e a execução fica como ``partial``.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from cauri_core.calendar import is_b3_trading_day
from cauri_ingest_market import store
from cauri_ingest_market.sources import bcb_sgs, coingecko, cotahist, tesouro
from cauri_storage import Conn, Pool, service_transaction

log = logging.getLogger("cauri.ingest")

COINGECKO_DEMO_MAX_DAYS = 365


@dataclass(frozen=True, slots=True)
class TrackedAsset:
    id: UUID
    ticker: str
    asset_class: str
    provider_ids: dict[str, Any]


@dataclass(slots=True)
class SourceResult:
    source: str
    status: str = "ok"
    requested: int = 0
    succeeded: int = 0
    failed: int = 0
    rows: int = 0
    error: str | None = None


@dataclass(slots=True)
class BackfillReport:
    run_id: UUID
    status: str
    sources: list[SourceResult] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return sum(s.rows for s in self.sources)


def tracked_assets(conn: Conn, tickers: Collection[str] | None) -> list[TrackedAsset]:
    """Ativos pedidos ou, sem lista, a UNIÃO das carteiras de todos os usuários (sem repetir).

    Preço de mercado é dado compartilhado: não importa de quem é a carteira.
    """
    if tickers is not None:
        rows = conn.execute(
            "select id, ticker, class, provider_ids from market.assets where ticker = any(%s)",
            [[t.upper() for t in tickers]],
        ).fetchall()
        missing = {t.upper() for t in tickers} - {r["ticker"] for r in rows}
        if missing:
            raise ValueError(f"ativos não cadastrados: {', '.join(sorted(missing))}")
    else:
        rows = conn.execute(
            "select distinct a.id, a.ticker, a.class, a.provider_ids"
            " from ledger.movements m join market.assets a on a.id = m.asset_id"
            " where m.voided_at is null"
        ).fetchall()
    return [TrackedAsset(r["id"], r["ticker"], r["class"], r["provider_ids"]) for r in rows]


def earliest_trade_date(conn: Conn) -> date | None:
    row = conn.execute(
        "select min(trade_date) as d from ledger.movements where voided_at is null"
    ).fetchone()
    return row["d"] if row else None


def run_backfill(
    pool: Pool,
    *,
    since: date,
    until: date,
    tickers: Collection[str] | None,
    client: httpx.Client,
    cache_dir: Path,
    coingecko_key: str | None,
    trigger: str = "manual",
    git_sha: str | None = None,
) -> BackfillReport:
    with service_transaction(pool) as conn:
        run_id = store.start_run(conn, "backfill", trigger, git_sha)
        assets = tracked_assets(conn, tickers)
    report = BackfillReport(run_id=run_id, status="ok")
    by_class: dict[str, list[TrackedAsset]] = {}
    for a in assets:
        by_class.setdefault(a.asset_class, []).append(a)

    steps: list[tuple[str, Callable[[Conn], SourceResult]]] = []
    b3 = by_class.get("acao", []) + by_class.get("fii", [])
    if b3:
        steps.append(
            ("cotahist", lambda c: _cotahist(c, run_id, b3, since, until, client, cache_dir))
        )
    if by_class.get("tesouro"):
        steps.append(
            ("tesouro", lambda c: _tesouro(c, run_id, by_class["tesouro"], since, until, client))
        )
    if by_class.get("cripto"):
        steps.append(
            (
                "coingecko",
                lambda c: _coingecko(
                    c, run_id, by_class["cripto"], since, until, client, coingecko_key
                ),
            )
        )
    steps.append(("bcb_sgs", lambda c: _indicators(c, run_id, since, until, client)))
    steps.append(("calendar", lambda c: _calendar(c, since, until + timedelta(days=60))))

    for source, step in steps:
        started = time.monotonic()
        try:
            with service_transaction(pool) as conn:
                result = step(conn)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            log.warning("fonte %s falhou: %s", source, exc)
            result = SourceResult(source=source, status="failed", failed=1, error=str(exc)[:500])
        duration = int((time.monotonic() - started) * 1000)
        with service_transaction(pool) as conn:
            store.record_source(
                conn,
                run_id,
                source,
                result.status,
                requested=result.requested,
                succeeded=result.succeeded,
                failed=result.failed,
                error_sample=result.error,
                duration_ms=duration,
            )
        report.sources.append(result)

    statuses = {s.status for s in report.sources}
    report.status = (
        "ok" if statuses == {"ok"} else ("failed" if statuses == {"failed"} else "partial")
    )
    with service_transaction(pool) as conn:
        store.finish_run(
            conn,
            run_id,
            report.status,
            {
                "since": since.isoformat(),
                "until": until.isoformat(),
                "assets": len(assets),
                "rows": report.rows,
            },
        )
    return report


def _cotahist(
    conn: Conn,
    run_id: UUID,
    assets: list[TrackedAsset],
    since: date,
    until: date,
    client: httpx.Client,
    cache_dir: Path,
) -> SourceResult:
    ids = {a.ticker: a.id for a in assets}
    result = SourceResult(source="cotahist", requested=len(assets))
    found: set[str] = set()
    for year in range(since.year, until.year + 1):
        path = cotahist.download(year, cache_dir, client, today=until)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows: list[store.PriceRow] = []
        raw_lines: list[str] = []
        for q in cotahist.iter_quotes(path, ids):
            if since <= q.trade_date <= until:
                rows.append(store.PriceRow(ids[q.ticker], q.trade_date, "BRL", q.close, "cotahist"))
                raw_lines.append(q.raw)
                found.add(q.ticker)
        store.save_raw(
            conn,
            run_id,
            "cotahist",
            {"url": cotahist.URL.format(year=year), "tickers": sorted(ids)},
            {"file_sha256": digest, "lines": raw_lines},
        )
        result.rows += store.upsert_prices(conn, rows, run_id)
    result.succeeded = len(found)
    result.failed = len(assets) - len(found)
    if result.failed:
        result.status = "partial"
        result.error = "sem cotação no período: " + ", ".join(sorted(set(ids) - found))
    return result


def _tesouro(
    conn: Conn,
    run_id: UUID,
    assets: list[TrackedAsset],
    since: date,
    until: date,
    client: httpx.Client,
) -> SourceResult:
    ids = {a.ticker: a.id for a in assets}
    text = tesouro.download(client)
    rows: list[store.PriceRow] = []
    raw_lines: list[str] = []
    found: set[str] = set()
    for price in tesouro.parse(text):
        ticker = tesouro.ticker_for(price.title_type, price.maturity)
        if ticker in ids and since <= price.base_date <= until:
            rows.append(
                store.PriceRow(ids[ticker], price.base_date, "BRL", price.pu_base, "tesouro")
            )
            raw_lines.append(price.raw)
            found.add(ticker)
    store.save_raw(
        conn,
        run_id,
        "tesouro",
        {"url": tesouro.URL, "tickers": sorted(ids)},
        {"file_sha256": hashlib.sha256(text.encode()).hexdigest(), "lines": raw_lines},
    )
    result = SourceResult(source="tesouro", requested=len(assets), succeeded=len(found))
    result.rows = store.upsert_prices(conn, rows, run_id)
    result.failed = len(assets) - len(found)
    if result.failed:
        result.status = "partial"
        result.error = "sem PU no período: " + ", ".join(sorted(set(ids) - found))
    return result


def _coingecko(
    conn: Conn,
    run_id: UUID,
    assets: list[TrackedAsset],
    since: date,
    until: date,
    client: httpx.Client,
    api_key: str | None,
) -> SourceResult:
    days = min((until - since).days + 2, COINGECKO_DEMO_MAX_DAYS)
    result = SourceResult(source="coingecko", requested=len(assets))
    errors: list[str] = []
    for asset in assets:
        coin_id = asset.provider_ids.get("coingecko")
        if not coin_id:
            result.failed += 1
            errors.append(f"{asset.ticker}: sem id do CoinGecko")
            continue
        try:
            for currency in ("brl", "usd"):
                time.sleep(6.5 if api_key is None else 0.5)  # sem chave: ~10 chamadas por minuto
                points, payload = coingecko.fetch_history(client, coin_id, currency, days, api_key)
                store.save_raw(
                    conn,
                    run_id,
                    "coingecko",
                    {"endpoint": "market_chart", "id": coin_id, "vs": currency, "days": days},
                    payload,
                )
                rows = [
                    store.PriceRow(asset.id, day, currency.upper(), price, "coingecko")
                    for day, price in points
                    if since <= day <= until and price > 0
                ]
                result.rows += store.upsert_prices(conn, rows, run_id)
            result.succeeded += 1
        except httpx.HTTPStatusError as exc:
            result.failed += 1
            errors.append(f"{asset.ticker}: HTTP {exc.response.status_code}")
            if exc.response.status_code == 429:
                break  # limite ainda estourado depois das novas tentativas: para aqui
    if result.failed:
        result.status = "failed" if result.succeeded == 0 else "partial"
        result.error = "; ".join(errors)[:500]
    return result


def _indicators(
    conn: Conn, run_id: UUID, since: date, until: date, client: httpx.Client
) -> SourceResult:
    result = SourceResult(source="bcb_sgs", requested=len(bcb_sgs.ALL))
    for series in bcb_sgs.ALL:
        start = since.replace(day=1) if series is bcb_sgs.IPCA else since
        points, raw = bcb_sgs.fetch(client, series, start, until)
        store.save_raw(conn, run_id, "bcb_sgs", {"series": series.name, "code": series.code}, raw)
        result.rows += store.upsert_indicators(conn, series.name, series.unit, points, run_id)
        result.succeeded += 1
    return result


def _calendar(conn: Conn, since: date, until: date) -> SourceResult:
    days = []
    day = since
    while day <= until:
        days.append((day, is_b3_trading_day(day)))
        day += timedelta(days=1)
    return SourceResult(
        source="calendar", requested=1, succeeded=1, rows=store.upsert_calendar(conn, days)
    )
