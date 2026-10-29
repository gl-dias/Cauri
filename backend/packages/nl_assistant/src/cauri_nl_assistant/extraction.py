"""O que o LLM devolve: só a frase entendida, nunca nada da carteira.

Cada operação tem seis campos: tipo, ativo como o usuário falou, quantidade, preço, moeda
e data. Números chegam como texto decimal com ponto ("0.01", "120000"), para nunca passarem
por float. Quem resolve "petrobras" para PETR4 e decide se precisa perguntar é o resolvedor,
em Python, com a carteira do usuário.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

KINDS = ("compra", "venda", "provento", "saldo_inicial", "outro")

TOOL_NAME = "registrar_operacoes"
TOOL = {
    "name": TOOL_NAME,
    "description": "Registra as operações de investimento que o usuário descreveu na frase.",
    "input_schema": {
        "type": "object",
        "properties": {
            "operacoes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tipo": {
                            "type": "string",
                            "enum": list(KINDS),
                            "description": "compra, venda, provento (dividendo, JCP, rendimento"
                            " recebido), saldo_inicial (posição que já tinha antes) ou outro.",
                        },
                        "ativo": {
                            "type": "string",
                            "description": "O ativo exatamente como o usuário falou: petrobras,"
                            " itau, PETR4, bitcoin, tesouro selic 2029. Não converta para"
                            " ticker.",
                        },
                        "quantidade": {
                            "type": ["string", "null"],
                            "description": "Número decimal com ponto, sem separador de milhar"
                            " ('0.01', '100'). Nulo se não foi dito.",
                        },
                        "preco": {
                            "type": ["string", "null"],
                            "description": "Preço unitário, decimal com ponto ('120000' para"
                            " '120 mil'). No provento, o valor total recebido. Nulo se não foi"
                            " dito.",
                        },
                        "moeda": {
                            "type": ["string", "null"],
                            "description": "Moeda do preço: BRL (reais), USD (dólares), USDT,"
                            " USDC, BTC... Nulo se não foi dita.",
                        },
                        "data": {
                            "type": ["string", "null"],
                            "description": "AAAA-MM-DD. Resolva 'ontem', 'segunda' etc. a"
                            " partir de hoje. Nulo se não foi dita.",
                        },
                    },
                    "required": ["tipo", "ativo", "quantidade", "preco", "moeda", "data"],
                },
            }
        },
        "required": ["operacoes"],
    },
}

SYSTEM = (
    "Você lê frases em português sobre operações de investimento (ações e FIIs da B3,"
    " Tesouro Direto e cripto) e registra cada operação com a ferramenta {tool}. Regras:"
    " devolva o ativo exatamente como foi falado, sem converter para ticker; não invente"
    " quantidade, preço, moeda nem data que não foram ditos (use nulo); 'mil' multiplica por"
    " 1000; 'reais' é BRL e 'dólares' é USD; se a frase não tiver nenhuma operação, devolva"
    " a lista vazia. Hoje é {today}."
)

_MONEY_WORDS = {
    "BRL": "BRL", "REAL": "BRL", "REAIS": "BRL", "R$": "BRL",
    "USD": "USD", "DOLAR": "USD", "DOLARES": "USD", "DÓLAR": "USD", "DÓLARES": "USD",
    "US$": "USD",
}  # fmt: skip


class ExtractionError(Exception):
    """O extrator não conseguiu entender a frase ou não respondeu. Mensagem para a tela."""


@dataclass(frozen=True, slots=True)
class SpokenOp:
    tipo: str
    ativo: str
    quantidade: Decimal | None = None
    preco: Decimal | None = None
    moeda: str | None = None
    data: date | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo,
            "ativo": self.ativo,
            "quantidade": _text(self.quantidade),
            "preco": _text(self.preco),
            "moeda": self.moeda,
            "data": self.data.isoformat() if self.data else None,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SpokenOp:
        """Valida o que veio do LLM (ou de uma edição): número inválido vira nulo."""
        tipo = str(data.get("tipo") or "outro").strip().lower()
        return cls(
            tipo=tipo if tipo in KINDS else "outro",
            ativo=str(data.get("ativo") or "").strip()[:80],
            quantidade=_decimal(data.get("quantidade")),
            preco=_decimal(data.get("preco")),
            moeda=_currency(data.get("moeda")),
            data=_date(data.get("data")),
        )


@dataclass(frozen=True, slots=True)
class Extraction:
    ops: tuple[SpokenOp, ...]
    model: str  # "claude-haiku-5-5" ou "regras"

    def to_json(self) -> dict[str, Any]:
        return {"operacoes": [op.to_json() for op in self.ops]}


class Extractor(Protocol):
    @property
    def model(self) -> str: ...

    def extract(self, text: str, today: date) -> Extraction: ...


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")  # o modelo às vezes devolve vírgula decimal
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() and number >= 0 else None


def _currency(value: Any) -> str | None:
    if not value:
        return None
    code = str(value).strip().upper()
    code = _MONEY_WORDS.get(code, code)
    return code if code.replace("$", "").isalnum() and len(code) <= 12 else None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
