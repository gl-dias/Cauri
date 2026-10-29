"""Extrator por regras, para desenvolvimento e testes sem chave da Anthropic.

Entende frases simples e diretas ("comprei 3 petrobras e vendi 2 itau", "comprei 0,01
bitcoin a 120 mil dólares ontem", "recebi 50 reais de itau"). Em produção quem extrai é o
Haiku; este extrator existe para o fluxo inteiro rodar e ser testado sem a API.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal

from cauri_nl_assistant.extraction import Extraction, SpokenOp

_VERBS = {"comprei": "compra", "vendi": "venda", "recebi": "provento", "tinha": "saldo_inicial"}
_WORD_NUMBERS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
    "sete": 7, "oito": 8, "nove": 9, "dez": 10, "cem": 100, "mil": 1000,
}  # fmt: skip
_CURRENCIES = {
    "reais": "BRL", "real": "BRL", "brl": "BRL", "dolares": "USD", "dolar": "USD",
    "usd": "USD", "usdt": "USDT", "usdc": "USDC", "btc": "BTC",
}  # fmt: skip
_NUM = r"\d+(?:[.,]\d+)*"
_SPLIT = re.compile(r"\s*(?:,|;|\be\b|\btambem\b)\s*(?=(?:comprei|vendi|recebi|tinha)\b)")
_DATE_WORDS = re.compile(r"\b(anteontem|ontem|hoje)\b")
_DATE_NUM = re.compile(r"\b(?:em|dia|no dia)\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_PRICE = re.compile(
    rf"\b(?:a|por|pagando|cada uma a|cada a)\s+(?:r\$\s*)?({_NUM})(\s*mil)?"
    r"(?:\s*(reais|real|brl|dolares|dolar|usd|usdt|usdc|btc))?\b"
)
_INCOME = re.compile(
    rf"^(?:r\$\s*)?({_NUM})(\s*mil)?\s*(reais|real|brl|dolares|dolar|usd|usdt|usdc)?"
    r"(?:\s+de\s+(?:dividendos?|jcp|juros|rendimentos?|proventos?))?\s+(?:de|do|da|dos|das)\s+(.+)$"
)
_QTY = re.compile(
    rf"^({_NUM}|{'|'.join(_WORD_NUMBERS)})\s+(?:(?:acoes|cotas|unidades)\s+)?(?:de\s+|do\s+|da\s+)?(.+)$"
)


def _plain(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(stripped.lower().split())


def _number(text: str, thousands: bool = False) -> Decimal:
    if text in _WORD_NUMBERS:
        value = Decimal(_WORD_NUMBERS[text])
    elif "," in text:
        value = Decimal(text.replace(".", "").replace(",", "."))
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        value = Decimal(text.replace(".", ""))  # 1.000 = mil
    else:
        value = Decimal(text)
    return value * 1000 if thousands else value


class RuleExtractor:
    model = "regras"

    def extract(self, text: str, today: date) -> Extraction:
        ops = [op for chunk in _SPLIT.split(_plain(text)) if (op := _chunk(chunk, today))]
        return Extraction(ops=tuple(ops), model=self.model)


def _chunk(chunk: str, today: date) -> SpokenOp | None:
    match = re.match(r"(comprei|vendi|recebi|tinha)\s+(.*)$", chunk.strip())
    if match is None:
        return None
    kind, rest = _VERBS[match.group(1)], match.group(2)

    day: date | None = None
    if found := _DATE_WORDS.search(rest):
        day = today - timedelta(days={"hoje": 0, "ontem": 1, "anteontem": 2}[found.group(1)])
        rest = rest[: found.start()] + rest[found.end() :]
    elif found := _DATE_NUM.search(rest):
        year = int(found.group(3)) if found.group(3) else today.year
        day = date(year + 2000 if year < 100 else year, int(found.group(2)), int(found.group(1)))
        rest = rest[: found.start()] + rest[found.end() :]
    rest = " ".join(rest.split())

    if kind == "provento":
        income = _INCOME.match(rest)
        if income is None:
            return SpokenOp(tipo="outro", ativo=rest, data=day)
        return SpokenOp(
            tipo="provento",
            ativo=income.group(4).strip(),
            preco=_number(income.group(1), bool(income.group(2))),
            moeda=_CURRENCIES.get(income.group(3) or ""),
            data=day,
        )

    price: Decimal | None = None
    currency: str | None = None
    if found := _PRICE.search(rest):
        price = _number(found.group(1), bool(found.group(2)))
        currency = _CURRENCIES.get(found.group(3) or "")
        rest = rest[: found.start()].strip()
    quantity_match = _QTY.match(rest)
    if quantity_match is None:
        return SpokenOp(tipo=kind, ativo=rest, preco=price, moeda=currency, data=day)
    return SpokenOp(
        tipo=kind,
        ativo=quantity_match.group(2).strip(),
        quantidade=_number(quantity_match.group(1)),
        preco=price,
        moeda=currency,
        data=day,
    )
