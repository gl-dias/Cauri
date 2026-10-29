"""Preços do Tesouro Direto pelo CSV oficial do Tesouro Transparente.

O arquivo traz todo o histórico, um título por linha e data base. Sai por volta das 10h
do dia seguinte, então no fim do dia D o PU mais recente é o de D-1.

Para avaliar a posição usamos o PU base da manhã (igual ao PU de venda/resgate na
prática). O ticker interno é ``TD-<TIPO>-<DDMMAAAA>``, por exemplo ``TD-IPCA-15052035``.
"""

from __future__ import annotations

import csv
import io
import time
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import httpx

from cauri_core.dates import SAO_PAULO
from cauri_core.money import parse_br_decimal

URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3"
    "/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
)

# Tipo do título no CSV (normalizado) -> (código no ticker, nome curto na tela)
_KINDS: dict[str, tuple[str, str]] = {
    "tesouro selic": ("SELIC", "Tesouro Selic"),
    "tesouro prefixado": ("PRE", "Tesouro Prefixado"),
    "tesouro prefixado com juros semestrais": ("PRE-JS", "Tesouro Prefixado com Juros Semestrais"),
    "tesouro ipca+": ("IPCA", "Tesouro IPCA+"),
    "tesouro ipca+ com juros semestrais": ("IPCA-JS", "Tesouro IPCA+ com Juros Semestrais"),
    "tesouro igpm+ com juros semestrais": ("IGPM-JS", "Tesouro IGP-M+ com Juros Semestrais"),
    "tesouro renda+ aposentadoria extra": ("RENDA", "Tesouro Renda+"),
    "tesouro educa+": ("EDUCA", "Tesouro Educa+"),
}


@dataclass(frozen=True, slots=True)
class TesouroPrice:
    title_type: str
    maturity: date
    base_date: date
    pu_buy: Decimal | None
    pu_sell: Decimal | None
    pu_base: Decimal
    raw: str


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(stripped.lower().split())


def _date(text: str) -> date:
    return datetime.strptime(text.strip(), "%d/%m/%Y").replace(tzinfo=SAO_PAULO).date()


def _optional(text: str) -> Decimal | None:
    value = parse_br_decimal(text) if text.strip() else None
    return value if value else None


def ticker_for(title_type: str, maturity: date) -> str | None:
    kind = _KINDS.get(_normalize(title_type))
    if kind is None:
        return None
    return f"TD-{kind[0]}-{maturity:%d%m%Y}"


def name_for(title_type: str, maturity: date) -> str:
    kind = _KINDS.get(_normalize(title_type))
    label = kind[1] if kind else title_type.strip()
    return f"{label} {maturity:%Y} ({maturity:%d/%m/%Y})"


def parse(text: str) -> Iterator[TesouroPrice]:
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader, None)
    if not header or _normalize(header[0]) != "tipo titulo":
        raise ValueError("cabeçalho inesperado no CSV do Tesouro")
    for row in reader:
        if len(row) < 8 or not row[0].strip():
            continue
        pu_base = parse_br_decimal(row[7])
        if pu_base <= 0:
            continue
        yield TesouroPrice(
            title_type=row[0].strip(),
            maturity=_date(row[1]),
            base_date=_date(row[2]),
            pu_buy=_optional(row[5]),
            pu_sell=_optional(row[6]),
            pu_base=pu_base,
            raw=";".join(row),
        )


_RETRY_WAITS_S = (5.0, 15.0)  # pausa antes da 2ª e da 3ª tentativa


def download(client: httpx.Client, *, sleep: Callable[[float], None] = time.sleep) -> str:
    """CSV de preços e taxas. Queda de conexão ou 5xx: até três tentativas."""
    for wait in (*_RETRY_WAITS_S, None):
        try:
            response = client.get(URL, timeout=300)
            if response.status_code < 500 or wait is None:
                response.raise_for_status()
                break
        except httpx.TransportError:
            if wait is None:
                raise
        sleep(wait)
    # O arquivo vem em latin-1 em alguns períodos; os nomes dos títulos usam acento.
    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError:
        return response.content.decode("latin-1")
