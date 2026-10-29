"""Séries do Banco Central (SGS): CDI, Selic meta, Selic efetiva, IPCA e PTAX de venda.

A PTAX de venda (série 1; a série 10813 é a de compra) converte para reais as operações
em dólar e em stablecoins. Sai por volta das 13h dos dias úteis.

Endpoint: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados
Séries diárias aceitam no máximo 10 anos por consulta; pedimos em janelas de 5.

A partir de IPs de datacenter (GitHub Actions), a API responde 200 com uma página HTML no
lugar do JSON quando as consultas se acumulam: num run, o CDI passou de primeira e as séries
seguintes falharam cada vez mais. Por isso há um intervalo mínimo entre consultas e esperas
longas antes de tentar de novo. Se todas as tentativas falharem, o erro mostra o título e o
texto da página que veio.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from cauri_core.dates import SAO_PAULO, add_months
from cauri_core.money import to_decimal

URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
RETRY_WAITS_S = (20.0, 60.0, 120.0)  # pausa antes da 2ª, 3ª e 4ª tentativa
MIN_INTERVAL_S = 3.0  # entre duas consultas quaisquer ao SGS, no mesmo processo

log = logging.getLogger("cauri.ingest")
_last_request = 0.0  # time.monotonic() da última consulta


class SgsError(Exception):
    """O SGS não devolveu a lista de pontos depois de todas as tentativas."""


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
    client: httpx.Client,
    series: Series,
    start: date,
    end: date,
    *,
    sleep: Callable[[float], None] = time.sleep,
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
        status, payload = _window(client, series, params, sleep)
        raw.append({"params": params, "status": status, "data": payload})
        points.update(parse(payload))
        window_start = window_end + timedelta(days=1)
    return sorted(points.items()), raw


def _window(
    client: httpx.Client,
    series: Series,
    params: dict[str, str],
    sleep: Callable[[float], None],
) -> tuple[int, list[dict[str, Any]]]:
    problem = ""
    for attempt in range(len(RETRY_WAITS_S) + 1):
        if attempt:
            log.warning(
                "SGS %s (%s): %s; tentando de novo em %.0f s",
                series.name, series.code, problem, RETRY_WAITS_S[attempt - 1],
            )  # fmt: skip
            sleep(RETRY_WAITS_S[attempt - 1])
        _pace(sleep)
        try:
            response = client.get(URL.format(code=series.code), params=params, timeout=60)
        except httpx.TransportError as exc:
            problem = f"sem resposta ({type(exc).__name__})"
            continue
        if response.status_code == 404:  # janela sem dados
            return 404, []
        if response.is_success:
            payload = _list(response)
            if payload is not None:
                return response.status_code, payload
        elif response.status_code != 429 and response.status_code < 500:
            response.raise_for_status()  # pedido errado: repetir não adianta
        problem = _describe(response)
    raise SgsError(
        f"SGS {series.name} ({series.code}) de {params['dataInicial']} a"
        f" {params['dataFinal']}: {problem}"
    )


def _pace(sleep: Callable[[float], None]) -> None:
    """Espera o que faltar para MIN_INTERVAL_S desde a última consulta."""
    global _last_request
    wait = _last_request + MIN_INTERVAL_S - time.monotonic()
    if wait > 0:
        sleep(wait)
    _last_request = time.monotonic()


def _list(response: httpx.Response) -> list[dict[str, Any]] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, list) else None


def _describe(response: httpx.Response) -> str:
    kind = response.headers.get("content-type", "sem content-type")
    text = response.text
    if "html" in kind.lower() or text.lstrip().startswith("<"):
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        body = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        body = re.sub(r"<[^>]+>", " ", body)
        text = f"título {' '.join(title.group(1).split()) if title else '(sem título)'}; {body}"
    summary = " ".join(text.split())[:240]
    return f"respondeu {response.status_code} ({kind}) sem a lista de pontos: {summary!r}"
