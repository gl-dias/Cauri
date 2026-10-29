"""Job diário de mercado: fechamento do dia de cada ativo da união das carteiras.

Duas passadas por dia útil (horário de Brasília): 18h30 e 19h30. A segunda só completa
o que ficou faltando na primeira (fechamento ainda não disponível, fonte fora do ar).

Fontes:
  * ações e FIIs: brapi (fechamento do dia, conferido pelo horário da cotação);
  * cripto: CoinGecko, preço em BRL e USD no momento da coleta (cripto não fecha);
  * Tesouro: CSV do Tesouro Transparente (o PU mais recente é o de D-1);
  * CDI, Selic e IPCA: SGS do Banco Central (últimos dias, para pegar o que saiu).

Cada fonte roda na sua transação e registra o status em ops.source_status.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID

import httpx

from cauri_core.calendar import is_b3_trading_day, previous_trading_day
from cauri_ingest_market import store
from cauri_ingest_market.backfill import SourceResult, TrackedAsset, tracked_assets
from cauri_ingest_market.sources import bcb_sgs, brapi, coingecko, tesouro
from cauri_storage import Conn, Pool, service_transaction

log = logging.getLogger("cauri.ingest")

ALL_SOURCES = frozenset({"brapi", "coingecko", "tesouro", "bcb_sgs"})
BRAPI_FREE_MONTHLY_QUOTA = 15_000


@dataclass(slots=True)
class DailyReport:
    run_id: UUID
    day: date
    second_pass: bool
    status: str = "ok"
    sources: list[SourceResult] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)  # tickers sem fechamento ainda


def _priced_on(conn: Conn, asset_ids: Collection[UUID], day: date) -> set[UUID]:
    if not asset_ids:
        return set()
    rows = conn.execute(
        "select asset_id from market.prices_daily"
        " where currency = 'BRL' and price_date = %s and asset_id = any(%s)",
        [day, list(asset_ids)],
    ).fetchall()
    return {r["asset_id"] for r in rows}


def _quota_used(conn: Conn, source: str, day: date) -> int:
    row = conn.execute(
        "select used from ops.quota_usage where source = %s and month = %s",
        [source, day.replace(day=1)],
    ).fetchone()
    return int(row["used"]) if row else 0


def _add_quota(conn: Conn, source: str, day: date, calls: int) -> None:
    conn.execute(
        "insert into ops.quota_usage (source, month, used) values (%s, %s, %s)"
        " on conflict (source, month) do update set used = ops.quota_usage.used + excluded.used",
        [source, day.replace(day=1), calls],
    )


def _brapi(
    conn: Conn,
    run_id: UUID,
    assets: list[TrackedAsset],
    day: date,
    client: httpx.Client,
    token: str | None,
    monthly_quota: int,
    pending: list[str],
    pause_s: float,
) -> SourceResult:
    result = SourceResult(source="brapi")
    if not is_b3_trading_day(day):
        result.status, result.error = "skipped", "sem pregão na B3 hoje"
        return result
    priced = _priced_on(conn, [a.id for a in assets], day)
    todo = [a for a in assets if a.id not in priced]
    result.requested = len(todo)
    if not todo:
        result.status = "skipped"
        return result

    used = _quota_used(conn, "brapi", day)
    rows: list[store.PriceRow] = []
    calls = 0
    no_trade: list[str] = []
    stopped_by_quota = False
    for i, asset in enumerate(todo):
        if used + calls >= monthly_quota:
            stopped_by_quota = True
            result.error = f"cota mensal da brapi esgotada ({monthly_quota} chamadas)"
            pending.extend(a.ticker for a in todo[i:])
            break
        quote = brapi.fetch_quote(client, asset.ticker, token, day)
        calls += 1
        store.save_raw(
            conn,
            run_id,
            "brapi",
            {"endpoint": "quote", "ticker": asset.ticker},
            quote.payload,
            quote.http_status,
        )
        match quote.outcome:
            case brapi.QuoteOutcome.CLOSE:
                assert quote.price is not None
                rows.append(store.PriceRow(asset.id, day, "BRL", quote.price, "brapi"))
            case brapi.QuoteOutcome.NOT_CLOSED_YET:
                pending.append(asset.ticker)
            case brapi.QuoteOutcome.STALE:
                no_trade.append(asset.ticker)  # sem negócio hoje: o engine usa o último preço
            case brapi.QuoteOutcome.QUOTA:
                stopped_by_quota = True
                result.error = (
                    f"brapi recusou por limite ou plano ({quote.error}); sem nova tentativa"
                )
                pending.extend(a.ticker for a in todo[i:])
                break
            case _:
                result.failed += 1
                result.error = f"{asset.ticker}: {quote.error or quote.outcome.value}"
        if pause_s:
            time.sleep(pause_s)

    _add_quota(conn, "brapi", day, calls)
    result.rows = store.upsert_prices(conn, rows, run_id)
    result.succeeded = len(rows)
    todo_tickers = {a.ticker for a in todo}
    waiting = [t for t in pending if t in todo_tickers]
    if stopped_by_quota:
        result.status = "quota_exceeded"
    elif waiting or result.failed:
        result.status = "partial" if rows else "failed"
        if waiting and not result.error:
            result.error = "fechamento ainda não disponível: " + ", ".join(waiting[:20])
    if no_trade:
        note = "sem negócio hoje: " + ", ".join(no_trade[:20])
        result.error = f"{result.error}; {note}" if result.error else note
    return result


def _coingecko(
    conn: Conn,
    run_id: UUID,
    assets: list[TrackedAsset],
    day: date,
    client: httpx.Client,
    api_key: str | None,
) -> SourceResult:
    already = _priced_on(conn, [a.id for a in assets], day)
    todo = [a for a in assets if a.id not in already]
    result = SourceResult(source="coingecko", requested=len(todo))
    if not todo:
        result.status = "skipped"
        return result
    by_coin = {str(a.provider_ids["coingecko"]): a for a in todo if a.provider_ids.get("coingecko")}
    missing_id = [a.ticker for a in todo if not a.provider_ids.get("coingecko")]
    payload = coingecko.fetch_simple(client, sorted(by_coin), api_key) if by_coin else {}
    store.save_raw(
        conn, run_id, "coingecko", {"endpoint": "simple/price", "ids": sorted(by_coin)}, payload
    )
    rows: list[store.PriceRow] = []
    for coin_id, asset in by_coin.items():
        prices = payload.get(coin_id) or {}
        for currency in ("brl", "usd"):
            value = prices.get(currency)
            if value:
                rows.append(
                    store.PriceRow(
                        asset.id, day, currency.upper(), coingecko.to_decimal(value), "coingecko"
                    )
                )
    result.rows = store.upsert_prices(conn, rows, run_id)
    priced = {r.asset_id for r in rows if r.currency == "BRL"}
    result.succeeded = len(priced)
    result.failed = len(todo) - len(priced)
    if result.failed:
        result.status = "partial" if priced else "failed"
        lacking = missing_id + [a.ticker for a in by_coin.values() if a.id not in priced]
        result.error = "sem preço: " + ", ".join(sorted(lacking))
    return result


def _tesouro(
    conn: Conn, run_id: UUID, assets: list[TrackedAsset], day: date, client: httpx.Client
) -> SourceResult:
    expected = (
        previous_trading_day(day)
        if is_b3_trading_day(day)
        else previous_trading_day(day + timedelta(days=1))
    )
    already = _priced_on(conn, [a.id for a in assets], expected)
    todo = [a for a in assets if a.id not in already]
    result = SourceResult(source="tesouro", requested=len(todo))
    if not todo:
        result.status = "skipped"
        return result
    ids = {a.ticker: a.id for a in todo}
    text = tesouro.download(client)
    since = day - timedelta(days=10)  # cobre o D-1 e eventuais dias que faltaram
    rows: list[store.PriceRow] = []
    raw_lines: list[str] = []
    for price in tesouro.parse(text):
        ticker = tesouro.ticker_for(price.title_type, price.maturity)
        if ticker in ids and since <= price.base_date <= day:
            rows.append(
                store.PriceRow(ids[ticker], price.base_date, "BRL", price.pu_base, "tesouro")
            )
            raw_lines.append(price.raw)
    store.save_raw(
        conn,
        run_id,
        "tesouro",
        {"url": tesouro.URL, "tickers": sorted(ids)},
        {"file_sha256": hashlib.sha256(text.encode()).hexdigest(), "lines": raw_lines},
    )
    result.rows = store.upsert_prices(conn, rows, run_id)
    fresh = {r.asset_id for r in rows if r.price_date >= expected}
    result.succeeded = len(fresh)
    result.failed = len(todo) - len(fresh)
    if result.failed:
        result.status = "partial" if fresh else "failed"
        result.error = f"PU de {expected:%d/%m} ainda não publicado para: " + ", ".join(
            sorted(t for t, i in ids.items() if i not in fresh)
        )
    return result


def _indicators(conn: Conn, run_id: UUID, day: date, client: httpx.Client) -> SourceResult:
    result = SourceResult(source="bcb_sgs", requested=len(bcb_sgs.ALL))
    for series in bcb_sgs.ALL:
        start = (
            (day - timedelta(days=70)).replace(day=1)
            if series is bcb_sgs.IPCA
            else day - timedelta(days=15)
        )
        points, raw = bcb_sgs.fetch(client, series, start, day)
        store.save_raw(conn, run_id, "bcb_sgs", {"series": series.name, "code": series.code}, raw)
        result.rows += store.upsert_indicators(conn, series.name, series.unit, points, run_id)
        result.succeeded += 1
    return result


def run_daily(
    pool: Pool,
    *,
    day: date,
    second_pass: bool,
    client: httpx.Client,
    brapi_token: str | None,
    coingecko_key: str | None,
    tickers: Collection[str] | None = None,
    sources: Collection[str] = ALL_SOURCES,
    brapi_monthly_quota: int = BRAPI_FREE_MONTHLY_QUOTA,
    brapi_pause_s: float = 0.2,
    trigger: str = "manual",
    git_sha: str | None = None,
) -> DailyReport:
    with service_transaction(pool) as conn:
        run_id = store.start_run(conn, "daily", trigger, git_sha)
        assets = tracked_assets(conn, tickers)
    report = DailyReport(run_id=run_id, day=day, second_pass=second_pass)
    by_class: dict[str, list[TrackedAsset]] = {}
    for a in assets:
        by_class.setdefault(a.asset_class, []).append(a)
    b3 = by_class.get("acao", []) + by_class.get("fii", [])

    steps: list[tuple[str, Callable[[Conn], SourceResult]]] = []
    if "brapi" in sources and b3:
        steps.append(
            (
                "brapi",
                lambda c: _brapi(
                    c,
                    run_id,
                    b3,
                    day,
                    client,
                    brapi_token,
                    brapi_monthly_quota,
                    report.pending,
                    brapi_pause_s,
                ),
            )
        )
    if "coingecko" in sources and by_class.get("cripto"):
        steps.append(
            (
                "coingecko",
                lambda c: _coingecko(c, run_id, by_class["cripto"], day, client, coingecko_key),
            )
        )
    if "tesouro" in sources and by_class.get("tesouro"):
        steps.append(("tesouro", lambda c: _tesouro(c, run_id, by_class["tesouro"], day, client)))
    if "bcb_sgs" in sources:
        steps.append(("bcb_sgs", lambda c: _indicators(c, run_id, day, client)))

    for source, step in steps:
        started = time.monotonic()
        try:
            with service_transaction(pool) as conn:
                result = step(conn)
        except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
            log.warning("fonte %s falhou: %s", source, exc)
            result = SourceResult(source=source, status="failed", failed=1, error=str(exc)[:500])
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
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        report.sources.append(result)

    statuses = {s.status for s in report.sources} - {"skipped"}
    if not statuses or statuses == {"ok"}:
        report.status = "ok"
    elif statuses == {"failed"}:
        report.status = "failed"
    else:
        report.status = "partial"
    with service_transaction(pool) as conn:
        store.finish_run(
            conn,
            run_id,
            report.status,
            {
                "day": day.isoformat(),
                "pass": "second" if second_pass else "first",
                "assets": len(assets),
                "pending": report.pending,
            },
        )
    return report
