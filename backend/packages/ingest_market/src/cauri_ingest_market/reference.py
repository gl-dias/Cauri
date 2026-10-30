"""Dados de referência: corretoras, criptoativos, ativos da B3 e do Tesouro, apelidos.

Tudo é idempotente (upsert): rodar de novo só atualiza nomes e marca ativos que
pararam de negociar como inativos, sem apagar nada.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from cauri_ingest_market.sources import cotahist, tesouro
from cauri_storage import Conn

# Ações (inclusive units), FIIs e ETFs: raiz de 4 caracteres + 1 ou 2 dígitos. BDRs já
# ficam de fora pelo código BDI (ver sources/cotahist.py).
_B3_TICKER = re.compile(r"^[A-Z0-9]{4}\d{1,2}$")
_ACTIVE_WINDOW = timedelta(days=30)
_B3_CLASSES = {cotahist.BDI_REITS: "fii", cotahist.BDI_FUNDS: "etf"}


def normalize_alias(text: str) -> str:
    """Minúsculas, sem acento e com espaços simples: "Itaú  Unibanco" vira "itau unibanco"."""
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(stripped.lower().split())


def sync_brokers(conn: Conn, items: Sequence[Mapping[str, str]]) -> int:
    for item in items:
        conn.execute(
            "insert into market.brokers (id, name, kind) values (%s, %s, %s)"
            " on conflict (id) do update set name = excluded.name, kind = excluded.kind",
            [item["id"], item["name"], item["kind"]],
        )
    return len(items)


def sync_crypto(conn: Conn, items: Sequence[Mapping[str, str]]) -> int:
    for item in items:
        conn.execute(
            "insert into market.assets (ticker, class, name, provider_ids)"
            " values (%s, 'cripto', %s, %s)"
            " on conflict (ticker) do update set name = excluded.name,"
            "   provider_ids = market.assets.provider_ids || excluded.provider_ids, active = true",
            [item["ticker"].upper(), item["name"], Jsonb({"coingecko": item["coingecko"]})],
        )
    return len(items)


@dataclass(frozen=True, slots=True)
class AliasReport:
    loaded: int
    skipped: list[str]


def sync_aliases(
    conn: Conn, issuers: Mapping[str, Sequence[str]], assets: Mapping[str, Sequence[str]]
) -> AliasReport:
    """Carrega apelidos. Apelido repetido entre alvos diferentes é erro (empresas nunca
    dividem apelido); alvo inexistente é pulado e informado."""
    targets: dict[str, tuple[str, str]] = {}
    for kind, mapping in (("issuer", issuers), ("asset", assets)):
        for target, aliases in mapping.items():
            for alias in aliases:
                norm = normalize_alias(alias)
                previous = targets.get(norm)
                if previous is not None and previous != (kind, target):
                    raise ValueError(f"apelido {alias!r} aponta para {previous[1]} e {target}")
                targets[norm] = (kind, target)

    known_issuers = {r["code"] for r in conn.execute("select code from market.issuers").fetchall()}
    asset_ids = {
        r["ticker"]: r["id"]
        for r in conn.execute(
            "select ticker, id from market.assets where ticker = any(%s)",
            [[t for k, t in targets.values() if k == "asset"]],
        ).fetchall()
    }
    loaded, skipped = 0, []
    for norm, (kind, target) in sorted(targets.items()):
        if kind == "issuer" and target not in known_issuers:
            skipped.append(f"{norm} -> {target}")
            continue
        if kind == "asset" and target not in asset_ids:
            skipped.append(f"{norm} -> {target}")
            continue
        conn.execute(
            "insert into market.asset_aliases (alias_norm, issuer_code, asset_id)"
            " values (%s, %s, %s)"
            " on conflict (alias_norm) do update"
            " set issuer_code = excluded.issuer_code, asset_id = excluded.asset_id",
            [
                norm,
                target if kind == "issuer" else None,
                asset_ids.get(target) if kind == "asset" else None,
            ],
        )
        loaded += 1
    return AliasReport(loaded=loaded, skipped=skipped)


@dataclass(frozen=True, slots=True)
class AssetSyncReport:
    issuers: int
    assets: int
    inactive: int


def sync_b3_assets(conn: Conn, zip_path: Path, etf_roots: Collection[str] = ()) -> AssetSyncReport:
    """Ações, FIIs e ETFs a partir do COTAHIST: último registro de cada ticker define nome e
    se ainda negocia (negociou nos últimos 30 dias do arquivo).

    No BDI de fundos (14) só entram os ETFs, pela raiz (``etf_roots``, da lista da B3 em
    ``reference/etfs.yaml``); FI-Infra e Fiagro ficam de fora."""
    roots = {r.upper() for r in etf_roots}
    latest: dict[str, cotahist.CotahistQuote] = {}
    for quote in cotahist.iter_quotes(zip_path):
        if not _B3_TICKER.match(quote.ticker):
            continue
        if quote.bdi == cotahist.BDI_FUNDS and quote.ticker[:4] not in roots:
            continue
        current = latest.get(quote.ticker)
        if current is None or quote.trade_date >= current.trade_date:
            latest[quote.ticker] = quote
    if not latest:
        return AssetSyncReport(0, 0, 0)
    last_day = max(q.trade_date for q in latest.values())

    issuer_names: dict[str, str] = {}
    for quote in sorted(latest.values(), key=lambda q: q.trade_date):
        issuer_names[quote.ticker[:4]] = quote.short_name.title()
    with conn.cursor() as cur:
        cur.executemany(
            "insert into market.issuers (code, name) values (%s, %s)"
            " on conflict (code) do update set name = excluded.name",
            sorted(issuer_names.items()),
        )
        rows: list[tuple[Any, ...]] = []
        inactive = 0
        for ticker, q in sorted(latest.items()):
            active = last_day - q.trade_date <= _ACTIVE_WINDOW
            inactive += not active
            asset_class = _B3_CLASSES.get(q.bdi, "acao")
            name = f"{q.short_name.title()} {q.spec}".strip()
            rows.append(
                (
                    ticker,
                    asset_class,
                    ticker[:4],
                    name,
                    Jsonb({"brapi": ticker, "isin": q.isin}),
                    active,
                )
            )
        cur.executemany(
            "insert into market.assets (ticker, class, issuer_code, name, provider_ids, active)"
            " values (%s, %s, %s, %s, %s, %s)"
            " on conflict (ticker) do update set name = excluded.name,"
            "   issuer_code = excluded.issuer_code, active = excluded.active,"
            "   provider_ids = market.assets.provider_ids || excluded.provider_ids",
            rows,
        )
    return AssetSyncReport(issuers=len(issuer_names), assets=len(latest), inactive=inactive)


def sync_tesouro_assets(conn: Conn, prices: Iterable[tesouro.TesouroPrice]) -> AssetSyncReport:
    """Títulos do Tesouro com preço publicado; ativo = tem preço nos últimos 30 dias."""
    latest: dict[str, tesouro.TesouroPrice] = {}
    for price in prices:
        ticker = tesouro.ticker_for(price.title_type, price.maturity)
        if ticker is None:
            continue
        current = latest.get(ticker)
        if current is None or price.base_date > current.base_date:
            latest[ticker] = price
    if not latest:
        return AssetSyncReport(0, 0, 0)
    last_day = max(p.base_date for p in latest.values())
    conn.execute(
        "insert into market.issuers (code, name) values ('TESOURO', 'Tesouro Nacional')"
        " on conflict (code) do nothing"
    )
    inactive = 0
    with conn.cursor() as cur:
        rows: list[tuple[Any, ...]] = []
        for ticker, p in sorted(latest.items()):
            active = last_day - p.base_date <= _ACTIVE_WINDOW and p.maturity > last_day
            inactive += not active
            rows.append(
                (
                    ticker,
                    tesouro.name_for(p.title_type, p.maturity),
                    p.maturity,
                    Jsonb({"tesouro": p.title_type}),
                    active,
                )
            )
        cur.executemany(
            "insert into market.assets"
            " (ticker, class, issuer_code, name, maturity_date, provider_ids, active)"
            " values (%s, 'tesouro', 'TESOURO', %s, %s, %s, %s)"
            " on conflict (ticker) do update set name = excluded.name, active = excluded.active,"
            "   maturity_date = excluded.maturity_date,"
            "   provider_ids = market.assets.provider_ids || excluded.provider_ids",
            rows,
        )
    return AssetSyncReport(issuers=1, assets=len(latest), inactive=inactive)
