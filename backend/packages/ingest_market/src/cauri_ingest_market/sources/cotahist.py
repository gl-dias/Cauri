"""COTAHIST: séries históricas oficiais da B3 (um arquivo ZIP por ano, texto de largura fixa).

Cada registro tem 245 caracteres. Usamos só o mercado à vista (TPMERC 010) dos códigos
BDI 02 (lote padrão: ações e units), 08 (empresas em recuperação judicial), 12 (fundos
imobiliários) e 14 (fundos de índice, junto com FI-Infra e Fiagro: quem separa os ETFs é a
lista da B3, ver ``b3_funds``). BDRs têm códigos próprios e ficam de fora por enquanto. O
próprio Ibovespa aparece no BDI 02 como IBOV11 (ISIN com tipo IND); índice não é ativo e
também fica de fora. ETFs de renda fixa (IMAB11, FIXA11) não estão no arquivo.

Preços vêm com duas casas implícitas e podem estar cotados por lote (FATCOT), então o
preço unitário é ``PREULT / 100 / FATCOT``.

O arquivo do ano corrente é atualizado pela B3 toda noite; o cache local respeita isso.
O download é grande (o do ano tem dezenas de MB) e a conexão às vezes cai no meio: a nova
tentativa continua de onde parou (o servidor aceita Range) e o ZIP é conferido no fim.
"""

from __future__ import annotations

import time
import zipfile
from collections.abc import Callable, Collection, Iterator
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
BDI_FUNDS = "14"
ISIN_INDEX = "IND"  # tipo do instrumento no ISIN (posições 7 a 9): BRIBOVINDM18
_BDIS = (BDI_STOCKS, BDI_JUDICIAL_RECOVERY, BDI_REITS, BDI_FUNDS)
_CURRENT_YEAR_MAX_AGE_S = 6 * 3600
_ATTEMPTS = 4
_RETRY_WAIT_S = 5.0  # multiplicado pelo número da tentativa


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
    if line[24:27] != SPOT_MARKET or bdi not in _BDIS:
        return None
    isin = line[230:242].strip()
    if isin[6:9] == ISIN_INDEX:
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
        isin=isin,
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


def download(
    year: int,
    cache_dir: Path,
    client: httpx.Client,
    *,
    today: date,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Baixa (ou reaproveita do cache) o ZIP do ano. O do ano corrente expira em 6 horas."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"COTAHIST_A{year}.ZIP"
    if target.exists():
        fresh = year < today.year or time.time() - target.stat().st_mtime < _CURRENT_YEAR_MAX_AGE_S
        if fresh:
            return target
    partial = target.with_suffix(".part")
    partial.unlink(missing_ok=True)
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            _fetch_into(client, URL.format(year=year), partial)
            break
        except httpx.TransportError:
            if attempt == _ATTEMPTS:
                raise
            sleep(_RETRY_WAIT_S * attempt)
    if not zipfile.is_zipfile(partial):
        partial.unlink()
        raise ValueError(f"COTAHIST {year}: o arquivo baixado não é um ZIP completo")
    partial.replace(target)
    return target


def _fetch_into(client: httpx.Client, url: str, partial: Path) -> None:
    """Baixa para ``partial``, continuando do tamanho que já tem quando o servidor aceita."""
    have = partial.stat().st_size if partial.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with client.stream("GET", url, headers=headers, timeout=300) as response:
        response.raise_for_status()
        resumed = response.status_code == 206  # com 200, o servidor mandou o arquivo todo
        with partial.open("ab" if resumed else "wb") as out:
            for chunk in response.iter_bytes():  # grava cada pedaço assim que chega
                out.write(chunk)
