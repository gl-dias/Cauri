"""O que o LLM devolve: só a frase entendida, nunca nada da carteira.

Cada operação tem sete campos: tipo, ativo como o usuário falou, quantidade, preço, moeda,
data e corretora. Números chegam como texto decimal com ponto ("0.01", "120000"), para
nunca passarem por float. Quem resolve "petrobras" para PETR4 e decide se precisa perguntar
é o resolvedor, em Python, com a carteira do usuário.

Com um cartão aberto na conversa, o LLM também recebe as frases anteriores do usuário (só o
que ele mesmo escreveu). Se a frase nova só completa ou corrige aquele cartão ("na XP, dia
29"), volta como ``complemento`` em vez de operação nova.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

KINDS = ("compra", "venda", "provento", "saldo_inicial", "outro")

TOOL_NAME = "registrar_operacoes"
_FIELDS: dict[str, Any] = {
    "quantidade": {
        "type": ["string", "null"],
        "description": "Número decimal com ponto, sem separador de milhar ('0.01', '100')."
        " Nulo se não foi dito.",
    },
    "preco": {
        "type": ["string", "null"],
        "description": "Preço unitário, decimal com ponto ('120000' para '120 mil'). No"
        " provento, o valor total recebido. Nulo se não foi dito.",
    },
    "moeda": {
        "type": ["string", "null"],
        "description": "Moeda do preço: BRL (reais), USD (dólares), USDT, USDC, BTC... Nulo se"
        " não foi dita.",
    },
    "data": {
        "type": ["string", "null"],
        "description": "AAAA-MM-DD, só se a frase disser quando foi ('hoje', 'ontem',"
        " 'segunda', 'dia 3'), resolvido a partir de hoje. Sem menção de data, nulo, mesmo em"
        " moeda estrangeira: a conversão é feita depois, pelo sistema.",
    },
    "corretora": {
        "type": ["string", "null"],
        "description": "Corretora, banco ou exchange como o usuário falou ('XP', 'Inter',"
        " 'Binance'). Nulo se não foi dita.",
    },
}
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
                        **_FIELDS,
                    },
                    "required": ["tipo", "ativo", *_FIELDS],
                },
            },
            "complemento": {
                "type": ["object", "null"],
                "description": "Só quando há frases anteriores (cartão aberto) e a frase nova"
                " apenas completa ou corrige aquela operação. Preencha só o que a frase nova"
                " diz; o resto fica nulo. Nulo nos outros casos.",
                "properties": {
                    "ativo": {
                        "type": ["string", "null"],
                        "description": "Ativo novo, como falado ('era IBOV11'). Nulo se não"
                        " foi dito.",
                    },
                    **_FIELDS,
                },
                "required": ["ativo", *_FIELDS],
            },
        },
        "required": ["operacoes", "complemento"],
    },
}

SYSTEM = (
    "Você lê frases em português sobre operações de investimento (ações e FIIs da B3,"
    " Tesouro Direto e cripto) e registra cada operação com a ferramenta {tool}. Regras:"
    " devolva o ativo e a corretora exatamente como foram falados, sem converter para ticker;"
    " não invente quantidade, preço, moeda, data nem corretora que não foram ditos (use"
    " nulo); 'mil' multiplica por 1000; 'reais' é BRL e 'dólares' é USD; a data vai"
    " preenchida sempre que a frase diz quando foi, inclusive 'hoje', e fica nula quando a"
    " frase não fala de data (nunca preencha a de hoje por conta própria, nem para converter"
    " moeda); se a frase não tiver nenhuma operação, devolva a lista vazia. Quando vierem"
    " frases anteriores da conversa, há um cartão aberto com aquela operação: se a frase nova"
    " só completa ou corrige o cartão ('na XP', 'foi dia 29', 'era IBOV11', 'a 38 reais'),"
    " deixe operacoes vazia e preencha complemento só com o que a frase nova diz; se ela"
    " descreve outra operação, registre em operacoes e deixe complemento nulo. Hoje é"
    " {today}."
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
    corretora: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo,
            "ativo": self.ativo,
            "quantidade": _text(self.quantidade),
            "preco": _text(self.preco),
            "moeda": self.moeda,
            "data": self.data.isoformat() if self.data else None,
            "corretora": self.corretora,
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
            corretora=_short(data.get("corretora")),
        )


@dataclass(frozen=True, slots=True)
class Complement:
    """O que uma frase de seguimento acrescenta ao cartão aberto: só os campos ditos."""

    ativo: str | None = None
    quantidade: Decimal | None = None
    preco: Decimal | None = None
    moeda: str | None = None
    data: date | None = None
    corretora: str | None = None

    @property
    def said(self) -> tuple[str, ...]:
        """Nomes dos campos que a frase trouxe, na ordem do cartão."""
        return tuple(k for k, v in self.to_json().items() if v is not None)

    def to_json(self) -> dict[str, Any]:
        return {
            "ativo": self.ativo,
            "quantidade": _text(self.quantidade),
            "preco": _text(self.preco),
            "moeda": self.moeda,
            "data": self.data.isoformat() if self.data else None,
            "corretora": self.corretora,
        }

    @classmethod
    def from_json(cls, data: Any) -> Complement | None:
        """Nulo quando não veio nada (ou só campos vazios)."""
        if not isinstance(data, Mapping):
            return None
        found = cls(
            ativo=_short(data.get("ativo")),
            quantidade=_decimal(data.get("quantidade")),
            preco=_decimal(data.get("preco")),
            moeda=_currency(data.get("moeda")),
            data=_date(data.get("data")),
            corretora=_short(data.get("corretora")),
        )
        return found if found.said else None


@dataclass(frozen=True, slots=True)
class Extraction:
    ops: tuple[SpokenOp, ...]
    model: str  # "claude-haiku-5-5" ou "regras"
    input_tokens: int = 0
    output_tokens: int = 0
    complement: Complement | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "operacoes": [op.to_json() for op in self.ops],
            "complemento": self.complement.to_json() if self.complement else None,
        }


class Extractor(Protocol):
    @property
    def model(self) -> str: ...

    def extract(self, text: str, today: date, context: Sequence[str] = ()) -> Extraction:
        """``context``: frases anteriores do usuário quando há cartão aberto na conversa."""
        ...


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


def _short(value: Any) -> str | None:
    text = " ".join(str(value or "").split())[:80]
    return text or None


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
