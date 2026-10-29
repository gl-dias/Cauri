"""COTAHIST: séries históricas oficiais da B3 (um arquivo ZIP por ano, texto de largura fixa).

Cada registro tem 245 caracteres. Usamos só o mercado à vista (TPMERC 010) dos códigos
BDI 02 (lote padrão: ações e units), 08 (empresas em recuperação judicial) e 12 (fundos
imobiliários). BDRs, ETFs e Fiagro têm códigos próprios e ficam de fora por enquanto.

Preços vêm com duas casas implícitas e podem estar cotados por lote (FATCOT), então o
preço unitário é ``PREULT / 100 / FATCOT``.

O arquivo do ano corrente é atualizado pela B3 toda noite; o cache local respeita isso.
"""

from __future__ import annotations

import time
import zipfile
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx

URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"
SPOT_MARKET = "010"
BDI_STOCKS = "02"
BDI_JUDICIAL_RECOVERY = "08"
BDI_REITS = "12"
_CURRENT_YEAR_MAX_AGE_S = 6 * 3600


@dataclass(frozen=True, slots=True)
class CotahistQuote:
    trade_date: date
    ticker: str
    bdi: str
    short_name: str  # NOMRES: "PETROBRAS", "ITAUUNIBANCO"
    spec: str  # ESPECI: "PN N2", "ON NM", "CI"
    close: Decimal
    isin: str
    raw: str


def parse_line(line: str) -> CotahistQuote | None:
    """Um registro de cotação, ou None se não for registro do mercado à vista que usamos."""
    if len(line) < 245 or line[0:2] != "01":
        return None
    bdi = line[10:12]
    if line[24:27] != SPOT_MARKET or bdi not in (BDI_STOCKS, BDI_JUDICIAL_RECOVERY, BDI_REITS):
        return None
    factor = int(line[210:217]) or 1
    close = Decimal(int(line[108:121])) / Decimal(100) / Decimal(factor)
    if close <= 0:
        return None
    return CotahistQuote(
        trade_date=date(int(line[2:6]), int(line[6:8]), int(line[8:10])),
        ticker=line[12:24].strip(),
        bdi=bdi,
        short_name=line[27:39].strip(),
        spec=" ".join(line[39:49].split()),
        close=close,
        isin=line[230:242].strip(),
        raw=line,
    )


def iter_quotes(zip_path: Path, tickers: Collection[str] | None = None) -> Iterator[CotahistQuote]:
    wanted = {t.upper() for t in tickers} if tickers is not None else None
    with zipfile.ZipFile(zip_path) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as handle:
            for raw in handle:
                line = raw.decode("latin-1").rstrip("\r\n")
                if wanted is not None and line[12:24].strip() not in wanted:
                    continue
                quote = parse_line(line)
                if quote is not None:
                    yield quote


def download(year: int, cache_dir: Path, client: httpx.Client, *, today: date) -> Path:
    """Baixa (ou reaproveita do cache) o ZIP do ano. O do ano corrente expira em 6 horas."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"COTAHIST_A{year}.ZIP"
    if target.exists():
        fresh = year < today.year or time.time() - target.stat().st_mtime < _CURRENT_YEAR_MAX_AGE_S
        if fresh:
            return target
    partial = target.with_suffix(".part")
    with client.stream("GET", URL.format(year=year), timeout=300) as response:
        response.raise_for_status()
        with partial.open("wb") as out:
            for chunk in response.iter_bytes(1 << 20):
                out.write(chunk)
    partial.replace(target)
    return target
