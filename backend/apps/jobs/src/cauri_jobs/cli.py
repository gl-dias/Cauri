"""CLI dos jobs: ``cauri-jobs <comando>``.

Ordem para um banco novo (o ``just seed`` faz isso):
    sync-reference -> sync-assets -> seed-demo -> bootstrap-admin

Todo dia útil (GitHub Actions): ``daily --pass first`` às 18h30 e ``daily --pass second``
às 19h30 (horário de Brasília). Localmente, as variáveis vêm do ``.env``.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from datetime import date, timedelta
from typing import Any

import httpx
import yaml
from dotenv import find_dotenv, load_dotenv

from cauri_core.dates import add_months, today_sp
from cauri_engine.persist import (
    clear_dirty,
    last_closed_day,
    recalc_user,
    take_dirty,
    users_for_daily,
)
from cauri_ingest_market import (
    run_backfill,
    run_daily,
    sync_aliases,
    sync_b3_assets,
    sync_brokers,
    sync_crypto,
    sync_tesouro_assets,
)
from cauri_ingest_market.backfill import earliest_trade_date
from cauri_ingest_market.sources import cotahist, tesouro
from cauri_jobs import seed
from cauri_jobs.config import ConfigError, JobsConfig
from cauri_jobs.demo import DEMO_B3_TICKERS, DEMO_CRYPTO_TICKERS
from cauri_storage import Pool, admin_connection, make_pool, service_transaction

log = logging.getLogger("cauri.jobs")


def _http() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": "cauri/0.1 (portal pessoal de investimentos)"}, follow_redirects=True
    )


def _yaml(cfg: JobsConfig, name: str) -> Any:
    with (cfg.reference_dir / name).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def cmd_sync_reference(cfg: JobsConfig, _: argparse.Namespace) -> None:
    pool = make_pool(cfg.ingest_url, max_size=1)
    with service_transaction(pool) as conn:
        brokers = sync_brokers(conn, _yaml(cfg, "brokers.yaml"))
        crypto = sync_crypto(conn, _yaml(cfg, "crypto.yaml"))
        aliases = _sync_aliases(cfg, conn)
    print(f"corretoras: {brokers} | criptoativos: {crypto} | apelidos: {aliases}")


def _sync_aliases(cfg: JobsConfig, conn: Any) -> str:
    data = _yaml(cfg, "aliases.yaml")
    report = sync_aliases(conn, data.get("issuers", {}), data.get("assets", {}))
    if report.skipped:
        log.info("apelidos sem ativo cadastrado (pulados): %s", ", ".join(report.skipped))
    return f"{report.loaded} carregados, {len(report.skipped)} pulados"


def cmd_sync_assets(cfg: JobsConfig, args: argparse.Namespace) -> None:
    today = today_sp()
    year = args.year or today.year
    pool = make_pool(cfg.ingest_url, max_size=1)
    with _http() as client:
        zip_path = cotahist.download(year, cfg.cache_dir, client, today=today)
        csv_text = tesouro.download(client)
    with service_transaction(pool) as conn:
        b3 = sync_b3_assets(conn, zip_path)
        td = sync_tesouro_assets(conn, tesouro.parse(csv_text))
        aliases = _sync_aliases(cfg, conn)
    print(
        f"B3: {b3.assets} ativos ({b3.inactive} inativos), {b3.issuers} emissores | "
        f"Tesouro: {td.assets} títulos ({td.inactive} inativos) | apelidos: {aliases}"
    )


def cmd_backfill(cfg: JobsConfig, args: argparse.Namespace) -> None:
    today = today_sp()
    pool = make_pool(cfg.ingest_url, max_size=2)
    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    with service_transaction(pool) as conn:
        since = args.since or earliest_trade_date(conn) or add_months(today, -12)
    until = args.until or today - timedelta(days=1)
    with _http() as client:
        report = run_backfill(
            pool,
            since=since,
            until=until,
            tickers=tickers,
            client=client,
            cache_dir=cfg.cache_dir,
            coingecko_key=cfg.coingecko_key,
            trigger=cfg.trigger,
            git_sha=cfg.git_sha,
        )
    for s in report.sources:
        extra = f" ({s.error})" if s.error else ""
        print(f"  {s.source:10} {s.status:15} {s.rows:6} linhas{extra}")
    print(f"backfill {since:%d/%m/%Y} a {until:%d/%m/%Y}: {report.status}")
    if report.status == "failed":
        sys.exit(1)


def recalc_users(
    pool: Pool, until: date, users: list[tuple[Any, date]]
) -> tuple[int, int, list[str]]:
    """Recalcula os snapshots de cada usuário na sua própria transação."""
    days = 0
    errors: list[str] = []
    for user_id, from_date in users:
        try:
            with service_transaction(pool) as conn:
                dirty = take_dirty(conn, user_id)
                start = min(from_date, dirty[0]) if dirty else from_date
                result = recalc_user(conn, user_id, from_date=start, until=until)
                if dirty:
                    clear_dirty(conn, user_id, dirty[1])
            days += result.days_written
        except Exception as exc:  # um usuário com problema não para os outros
            log.exception("recálculo falhou para %s", user_id)
            errors.append(f"{user_id}: {exc}")
    return len(users), days, errors


def cmd_daily(cfg: JobsConfig, args: argparse.Namespace) -> None:
    day = args.date or today_sp()
    second = args.pass_ == "second"
    pool = make_pool(cfg.ingest_url, max_size=2)
    with _http() as client:
        report = run_daily(
            pool,
            day=day,
            second_pass=second,
            client=client,
            brapi_token=cfg.brapi_token,
            coingecko_key=cfg.coingecko_key,
            brapi_monthly_quota=cfg.brapi_monthly_quota,
            trigger=cfg.trigger,
            git_sha=cfg.git_sha,
        )
    for s in report.sources:
        extra = f" ({s.error})" if s.error else ""
        print(f"  {s.source:10} {s.status:15} {s.rows:5} linhas{extra}")
    with service_transaction(pool) as conn:
        users = users_for_daily(conn, day)
    count, days, errors = recalc_users(pool, day, users)
    print(f"mercado {day:%d/%m/%Y} ({'2a' if second else '1a'} passada): {report.status}")
    print(f"snapshots: {count} carteiras, {days} dias regravados")
    if report.pending:
        print(f"sem fechamento ainda: {', '.join(report.pending[:20])}")
    if report.status == "failed" or errors:
        sys.exit(1)


def cmd_recalc(cfg: JobsConfig, args: argparse.Namespace) -> None:
    until = last_closed_day()
    pool = make_pool(cfg.ingest_url, max_size=2)
    with service_transaction(pool) as conn:
        if args.user:
            users = [(args.user, args.from_date or date(1990, 1, 1))]
        else:
            rows = conn.execute("select distinct user_id from ledger.movements").fetchall()
            users = [(r["user_id"], args.from_date or date(1990, 1, 1)) for r in rows]
    count, days, errors = recalc_users(pool, until, users)
    print(f"snapshots até {until:%d/%m/%Y}: {count} carteiras, {days} dias regravados")
    if errors:
        sys.exit(1)


def cmd_bootstrap_admin(cfg: JobsConfig, _: argparse.Namespace) -> None:
    with admin_connection(cfg.admin_url) as conn:
        seed.bootstrap_admin(conn, cfg.admin_email)
    print("admin configurado (e-mail lido de CAURI_ADMIN_EMAIL)")


def cmd_seed_demo(cfg: JobsConfig, args: argparse.Namespace) -> None:
    today = today_sp()
    since = add_months(today, -args.months) - timedelta(days=15)
    with admin_connection(cfg.admin_url) as conn:
        demo_id = seed.ensure_demo_user(conn)
        existing = seed.active_demo_movements(conn, demo_id)
        if existing and not args.reset:
            print(f"o demo já tem {existing} movimentações; use --reset para gerar de novo")
            return
        tesouro_pair = seed.pick_tesouro(conn, today)
    tickers = [*DEMO_B3_TICKERS, *DEMO_CRYPTO_TICKERS, *tesouro_pair]

    print(f"buscando histórico de preços reais de {len(tickers)} ativos...")
    pool = make_pool(cfg.ingest_url, max_size=2)
    with _http() as client:
        report = run_backfill(
            pool,
            since=since,
            until=today - timedelta(days=1),
            tickers=tickers,
            client=client,
            cache_dir=cfg.cache_dir,
            coingecko_key=cfg.coingecko_key,
            trigger=cfg.trigger,
            git_sha=cfg.git_sha,
        )
    if report.status != "ok":
        failed = ", ".join(f"{s.source}: {s.error}" for s in report.sources if s.status != "ok")
        raise SystemExit(f"backfill incompleto, demo não gerado ({failed})")

    with admin_connection(cfg.admin_url) as conn:
        if existing:
            voided = seed.reset_demo(conn, demo_id)
            print(f"reset: {voided} movimentações antigas removidas (soft delete)")
        closes = seed.load_closes(conn, tickers, since)
        result = seed.seed_demo(conn, demo_id, closes, today=today, tesouro=tesouro_pair)
    print(f"demo: {result.created} movimentações em {result.batches} lotes")
    _, days, errors = recalc_users(pool, last_closed_day(), [(demo_id, date(1990, 1, 1))])
    print(f"snapshots do demo: {days} dias" + (f" (erros: {errors})" if errors else ""))


def main(argv: list[str] | None = None) -> None:
    load_dotenv(find_dotenv(usecwd=True), override=False)  # local; no Actions vêm dos secrets
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(
        logging.WARNING
    )  # a URL da brapi não leva token, mas evita ruído
    parser = argparse.ArgumentParser(prog="cauri-jobs", description="Jobs do Cauri")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync-reference", help="corretoras, criptoativos e apelidos (reference/)")
    p = sub.add_parser("sync-assets", help="ações e FIIs (COTAHIST) e títulos do Tesouro")
    p.add_argument("--year", type=int, help="ano do COTAHIST (padrão: o atual)")
    p = sub.add_parser("backfill", help="histórico de preços e indicadores")
    p.add_argument("--since", type=date.fromisoformat, help="AAAA-MM-DD (padrão: 1a movimentação)")
    p.add_argument("--until", type=date.fromisoformat, help="AAAA-MM-DD (padrão: ontem)")
    p.add_argument("--tickers", help="lista separada por vírgula (padrão: união das carteiras)")
    sub.add_parser("bootstrap-admin", help="coloca CAURI_ADMIN_EMAIL na allowlist como admin")
    p = sub.add_parser("daily", help="fechamento do dia e snapshots (job das 18h30 e 19h30)")
    p.add_argument("--pass", dest="pass_", choices=["first", "second"], default="first")
    p.add_argument("--date", type=date.fromisoformat, help="AAAA-MM-DD (padrão: hoje em Brasília)")
    p = sub.add_parser("recalc", help="recalcula snapshots (todas as carteiras ou uma)")
    p.add_argument("--user", type=uuid.UUID, help="id do usuário (padrão: todos)")
    p.add_argument("--from", dest="from_date", type=date.fromisoformat, help="AAAA-MM-DD")
    p = sub.add_parser("seed-demo", help="usuário demo com carteira fictícia e preços reais")
    p.add_argument(
        "--reset", action="store_true", help="remove o ledger atual do demo e gera de novo"
    )
    p.add_argument("--months", type=int, default=12)

    args = parser.parse_args(argv)
    commands = {
        "sync-reference": cmd_sync_reference,
        "sync-assets": cmd_sync_assets,
        "backfill": cmd_backfill,
        "bootstrap-admin": cmd_bootstrap_admin,
        "seed-demo": cmd_seed_demo,
        "daily": cmd_daily,
        "recalc": cmd_recalc,
    }
    try:
        commands[args.command](JobsConfig(), args)
    except ConfigError as exc:
        raise SystemExit(f"configuração: {exc}") from exc


if __name__ == "__main__":
    main()
