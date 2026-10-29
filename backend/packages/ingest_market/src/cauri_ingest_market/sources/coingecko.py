"""Preços de cripto em BRL e USD pelo CoinGecko (plano Demo, uso pessoal).

O histórico diário vem com um ponto às 00h UTC de cada dia, que corresponde às 21h do
dia anterior em Brasília; gravamos esse ponto como o fechamento do dia anterior. O
plano Demo exige o crédito "Data provided by CoinGecko" na interface.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx

from cauri_core.dates import SAO_PAULO

BASE_URL = "https://api.coingecko.com/api/v3"
# Limite por minuto atingido (429): no máximo duas novas tentativas, esperando o que a
# API pedir (Retry-After), com teto. Nada de insistir para sempre.
MAX_RETRIES_ON_429 = 2
MAX_WAIT_S = 65.0


def _headers(api_key: str | None) -> dict[str, str]:
    return {"x-cg-demo-api-key": api_key} if api_key else {}


def _get(
    client: httpx.Client, url: str, params: Mapping[str, str | int], api_key: str | None
) -> httpx.Response:
    for attempt in range(MAX_RETRIES_ON_429 + 1):
        response = client.get(url, params=params, headers=_headers(api_key), timeout=60)
        if response.status_code != 429 or attempt == MAX_RETRIES_ON_429:
            break
        retry_after = response.headers.get("Retry-After", "")
        wait = float(retry_after) if retry_after.isdigit() else 30.0
        time.sleep(min(wait, MAX_WAIT_S))
    response.raise_for_status()
    return response


def parse_history(payload: dict[str, Any]) -> list[tuple[date, Decimal]]:
    """Pontos ``[ms, preço]`` viram ``(data em Brasília, preço)``; o último de cada dia vale."""
    by_day: dict[date, Decimal] = {}
    for ms, price in payload.get("prices", []):
        moment = datetime.fromtimestamp(ms / 1000, tz=UTC).astimezone(SAO_PAULO)
        # repr evita levar o erro binário do float da resposta para o Decimal.
        by_day[moment.date()] = Decimal(repr(price))
    return sorted(by_day.items())


def fetch_history(
    client: httpx.Client, coin_id: str, vs_currency: str, days: int, api_key: str | None
) -> tuple[list[tuple[date, Decimal]], dict[str, Any]]:
    response = _get(
        client,
        f"{BASE_URL}/coins/{coin_id}/market_chart",
        {"vs_currency": vs_currency, "days": days, "interval": "daily"},
        api_key,
    )
    payload: dict[str, Any] = response.json()
    return parse_history(payload), payload


def fetch_simple(
    client: httpx.Client, coin_ids: Sequence[str], api_key: str | None
) -> dict[str, Any]:
    """Preço atual de vários ativos em BRL e USD numa chamada só (usado no job diário)."""
    response = _get(
        client,
        f"{BASE_URL}/simple/price",
        {"ids": ",".join(coin_ids), "vs_currencies": "brl,usd"},
        api_key,
    )
    result: dict[str, Any] = response.json()
    return result
