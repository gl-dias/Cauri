"""Fechamento diário de ações, FIIs e ETFs pela brapi.dev (plano gratuito: 1 ativo por chamada).

Só serve para o preço do dia: o plano gratuito tem 3 meses de histórico, então o
histórico vem do COTAHIST.

Regras:
* o token vai no header ``Authorization`` e nunca é gravado nem logado;
* limite/cota atingido (429) ou plano sem acesso (402/403) interrompe a brapi no resto
  da execução, sem nova tentativa;
* erro de rede ou 5xx ganha no máximo uma nova tentativa;
* a cotação só vale como fechamento se for do dia e posterior ao início do call de
  fechamento (o plano gratuito tem uns 30 minutos de atraso). Antes disso ela fica
  pendente, e a segunda passada completa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import httpx

from cauri_core.dates import SAO_PAULO
from cauri_core.session import closing_call_start

BASE_URL = "https://brapi.dev/api/quote"
QUOTA_STATUSES = frozenset({402, 403, 429})


class QuoteOutcome(StrEnum):
    CLOSE = "close"  # fechamento do dia, pode gravar
    NOT_CLOSED_YET = "not_closed_yet"  # cotação de antes do fim do pregão
    STALE = "stale"  # cotação de outro dia (feriado, ativo sem negócio)
    NOT_FOUND = "not_found"
    QUOTA = "quota"  # limite atingido ou plano sem acesso: para a brapi
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class QuoteResult:
    ticker: str
    outcome: QuoteOutcome
    price: Decimal | None = None
    market_time: datetime | None = None
    http_status: int | None = None
    payload: Any = None
    error: str | None = None


def parse_quote(ticker: str, payload: dict[str, Any], day: date) -> QuoteResult:
    results = payload.get("results") or []
    item = next((r for r in results if str(r.get("symbol", "")).upper() == ticker), None)
    if item is None or item.get("regularMarketPrice") is None:
        return QuoteResult(ticker, QuoteOutcome.NOT_FOUND, payload=payload)
    # repr evita levar o erro binário do float da resposta para o Decimal.
    price = Decimal(repr(item["regularMarketPrice"]))
    raw_time = item.get("regularMarketTime")
    if not raw_time or price <= 0:
        return QuoteResult(
            ticker, QuoteOutcome.ERROR, payload=payload, error="cotação sem horário ou preço"
        )
    market_time = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00")).astimezone(SAO_PAULO)
    if market_time.date() != day:
        outcome = QuoteOutcome.STALE
    elif market_time < closing_call_start(day):
        outcome = QuoteOutcome.NOT_CLOSED_YET
    else:
        outcome = QuoteOutcome.CLOSE
    return QuoteResult(
        ticker, outcome, price=price, market_time=market_time, http_status=200, payload=payload
    )


def fetch_quote(client: httpx.Client, ticker: str, token: str | None, day: date) -> QuoteResult:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    last_error = ""
    for _attempt in range(2):  # uma nova tentativa só para rede/5xx
        try:
            response = client.get(f"{BASE_URL}/{ticker}", headers=headers, timeout=30)
        except httpx.TransportError as exc:
            last_error = f"rede: {type(exc).__name__}"
            continue
        if response.status_code in QUOTA_STATUSES:
            return QuoteResult(
                ticker,
                QuoteOutcome.QUOTA,
                http_status=response.status_code,
                payload=_json_or_text(response),
                error=f"HTTP {response.status_code}",
            )
        if response.status_code == 404:
            return QuoteResult(
                ticker, QuoteOutcome.NOT_FOUND, http_status=404, payload=_json_or_text(response)
            )
        if response.status_code >= 500:
            last_error = f"HTTP {response.status_code}"
            continue
        if response.status_code != 200:
            return QuoteResult(
                ticker,
                QuoteOutcome.ERROR,
                http_status=response.status_code,
                payload=_json_or_text(response),
                error=f"HTTP {response.status_code}",
            )
        return parse_quote(ticker, response.json(), day)
    return QuoteResult(ticker, QuoteOutcome.ERROR, error=last_error)


def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"text": response.text[:500]}
