"""Haiku de verdade (opcional): só roda com CAURI_LLM_LIVE=1 e ANTHROPIC_API_KEY.

Confere que o modelo devolve os seis campos das frases de exemplo. Custa centavos; fica
fora do CI de propósito (sem chave lá). Rodar com ``just test-llm``.
"""

import os
from datetime import date
from decimal import Decimal

import pytest

from cauri_nl_assistant import AnthropicExtractor

pytestmark = pytest.mark.skipif(
    os.environ.get("CAURI_LLM_LIVE") != "1" or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="só com CAURI_LLM_LIVE=1 e ANTHROPIC_API_KEY",
)
TODAY = date(2026, 10, 29)


@pytest.fixture(scope="module")
def haiku():
    return AnthropicExtractor(
        os.environ["ANTHROPIC_API_KEY"],
        model=os.environ.get("CAURI_ANTHROPIC_MODEL", "claude-haiku-5-5"),
    )


def test_frase_da_especificacao(haiku):
    ops = haiku.extract("comprei 3 petrobras e vendi 2 itau", TODAY).ops
    assert [(o.tipo, o.ativo.lower(), o.quantidade) for o in ops] == [
        ("compra", "petrobras", Decimal(3)),
        ("venda", "itau", Decimal(2)),
    ]


def test_cripto_em_dolar(haiku):
    [op] = haiku.extract("comprei 0,01 bitcoin a 120 mil dólares", TODAY).ops
    assert (op.tipo, op.quantidade, op.preco, op.moeda) == (
        "compra",
        Decimal("0.01"),
        Decimal(120000),
        "USD",
    )


def test_data_relativa_e_sem_operacao(haiku):
    [op] = haiku.extract("ontem vendi 10 PETR4 a 38,50", TODAY).ops
    assert (op.data, op.preco) == (date(2026, 10, 28), Decimal("38.50"))
    assert haiku.extract("bom dia, tudo bem?", TODAY).ops == ()
