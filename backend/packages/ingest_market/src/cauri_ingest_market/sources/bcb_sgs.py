"""Séries do Banco Central (SGS): CDI, Selic meta, Selic efetiva, IPCA e PTAX de venda.

A PTAX de venda (série 1; a série 10813 é a de compra) converte para reais as operações
em dólar e em stablecoins. Sai por volta das 13h dos dias úteis.

Endpoint: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados
Séries diárias aceitam no máximo 10 anos por consulta; pedimos em janelas de 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from cauri_core.dates import SAO_PAULO, add_months
from cauri_core.money import to_decimal

URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"


@dataclass(frozen=True, slots=True)
class Series:
    name: str  # valor do enum market.indicator_series
    code: int
    unit: str


CDI = Series("CDI", 12, "% a.d.")
SELIC_META = Series("SELIC_META", 432, "% a.a.")
SELIC_EFETIVA = Series("SELIC_EFETIVA", 1178, "% a.a.")
IPCA = Series("IPCA", 433, "% a.m.")
PTAX_VENDA = Series("PTAX_VENDA", 1, "R$/US$")
ALL = (CDI, SELIC_META, SELIC_EFETIVA, IPCA, PTAX_VENDA)


def parse(payload: list[dict[str, Any]]) -> list[tuple[date, Decimal]]:
    points: list[tuple[date, Decimal]] = []
    for item in payload:
        day = datetime.strptime(item["data"], "%d/%m/%Y").replace(tzinfo=SAO_PAULO).date()
        points.append((day, to_decimal(str(item["valor"]))))
    return points


def fetch(
    client: httpx.Client, series: Series, start: date, end: date
) -> tuple[list[tuple[date, Decimal]], list[dict[str, Any]]]:
    """Pontos da série no intervalo e as respostas cruas (para o raw)."""
    points: dict[date, Decimal] = {}
    raw: list[dict[str, Any]] = []
    window_start = start
    while window_start <= end:
        window_end = min(end, add_months(window_start, 60) - timedelta(days=1))
        params = {
            "formato": "json",
            "dataInicial": f"{window_start:%d/%m/%Y}",
            "dataFinal": f"{window_end:%d/%m/%Y}",
        }
        response = client.get(URL.format(code=series.code), params=params, timeout=60)
        if response.status_code == 404:  # janela sem dados
            payload: list[dict[str, Any]] = []
        else:
            response.raise_for_status()
            payload = response.json()
        raw.append({"params": params, "status": response.status_code, "data": payload})
        points.update(parse(payload))
        window_start = window_end + timedelta(days=1)
    return sorted(points.items()), raw
