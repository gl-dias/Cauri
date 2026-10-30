"""Lista de ETFs da B3 (fundos de índice), pelo serviço que alimenta o site da B3.

O COTAHIST põe ETFs, FI-Infra e Fiagro no mesmo código BDI 14, com a mesma especificação
(CI); só a lista de fundos da B3 diz quem é ETF. O serviço não é documentado (já mudou de
formato uma vez) e fica atrás do Cloudflare, então não roda nos jobs agendados:
``cauri-jobs etf-list`` grava ``reference/etfs.yaml``, que vai para o repositório e é o que
a carga do cadastro lê.

A lista traz a raiz de negociação ("BOVA"), não o ticker; no COTAHIST o ETF é a raiz + 11.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

URL = "https://sistemaswebb3-listados.b3.com.br/fundsListedProxy/Search/GetListFunds/{query}"
# Renda variável, renda fixa, cripto, renda fixa internacional e índice de FIIs.
ETF_TYPES = ("ETF", "ETF-RF", "ETF-CRIPTO", "ETF-INT-RF", "ETF-FII")
PAGE_SIZE = 120  # o máximo: acima disso o serviço devolve lista vazia, sem erro
MIN_EXPECTED = 100  # em 30/10/2026 eram 238; bem menos que isso é resposta quebrada
_ROOT = re.compile(r"^[A-Z0-9]{4}$")


@dataclass(frozen=True, slots=True)
class ListedEtf:
    root: str  # BOVA
    kind: str  # ETF, ETF-RF...
    name: str  # nome de pregão: "ISHARES BOVA"


def query(kind: str, page: int) -> str:
    body = {"language": "pt-br", "typeFund": kind, "pageNumber": page, "pageSize": PAGE_SIZE}
    return base64.b64encode(json.dumps(body).encode()).decode()


def parse_page(data: Mapping[str, Any], kind: str) -> tuple[list[ListedEtf], int]:
    """Os ETFs de uma página e o total de páginas."""
    found = []
    for row in data.get("results") or []:
        root = str(row.get("acronym") or "").strip().upper()
        if _ROOT.match(root):
            name = " ".join(str(row.get("tradingName") or row.get("fundName") or root).split())
            found.append(ListedEtf(root, kind, name))
    pages = int((data.get("page") or {}).get("totalPages") or 0)
    return found, pages


def fetch_etfs(client: httpx.Client) -> list[ListedEtf]:
    found: dict[str, ListedEtf] = {}
    for kind in ETF_TYPES:
        page = 1
        while True:
            response = client.get(URL.format(query=query(kind, page)), timeout=30)
            response.raise_for_status()
            etfs, pages = parse_page(response.json(), kind)
            for etf in etfs:
                found.setdefault(etf.root, etf)
            if page >= pages:
                break
            page += 1
    if len(found) < MIN_EXPECTED:
        raise ValueError(
            f"Lista de ETFs da B3 com só {len(found)} fundos (esperado {MIN_EXPECTED} ou mais):"
            " o serviço deve ter mudado. A lista anterior continua valendo."
        )
    return sorted(found.values(), key=lambda e: e.root)
