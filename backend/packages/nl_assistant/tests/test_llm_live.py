"""Haiku de verdade (opcional): só roda com CAURI_LLM_LIVE=1 e ANTHROPIC_API_KEY.

Cada frase de exemplo (especificação, cripto, ambiguidade, venda descoberta, provento,
saldo inicial, data relativa, corretora e frase sem operação) passa pelo Haiku e pelo
extrator por regras. O Haiku precisa acertar tudo o que as regras acertam: mesmos tipos,
ativos e corretoras como falados, quantidades, preços, moedas e datas. As frases de
seguimento (com cartão aberto) viram complemento, não operação nova. Custa centavos; fica
fora do CI de propósito. Rodar com ``just test-llm``.
"""

import os
from datetime import date
from decimal import Decimal

import pytest

from cauri_nl_assistant import AnthropicExtractor, Complement, RuleExtractor, SpokenOp
from cauri_nl_assistant.resolver import normalize

pytestmark = pytest.mark.skipif(
    os.environ.get("CAURI_LLM_LIVE") != "1" or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="só com CAURI_LLM_LIVE=1 e ANTHROPIC_API_KEY",
)
TODAY = date(2011, 3, 10)

PHRASES = [
    # especificação
    "comprei 3 petrobras e vendi 2 itau",
    "comprei 10 PETR4 a 38,45 ontem",
    # cripto e moeda estrangeira
    "comprei 0,01 bitcoin a 120 mil dólares",
    "comprei 0,01 bitcoin a 60000 usdt",
    # ambiguidade (a resolução é do Python; aqui importa o ativo como falado)
    "comprei 1 petrobras a 30",
    "comprei 1 itau a 30 reais",
    "comprei 1 itausa a 10",
    # venda descoberta (a trava é do ledger; aqui importa a extração)
    "vendi 100 PETR4 a 31",
    # provento e saldo inicial
    "recebi 50 reais de dividendos do itau",
    "tinha 150 usdt a 5,30 em 01/03/2011",
    # data (inclusive "hoje", dita) e frase sem operação
    "comprei 2 PETR4 anteontem",
    "comprei 1 PETR4 hoje por 30",
    "bom dia, como vai a carteira?",
    # corretora dita
    "comprei 10 PETR4 a 30 na xp",
    "comprei 0,01 bitcoin a 120 mil dólares pela binance",
]
# Seguimentos: (frases anteriores, frase nova, complemento esperado)
FOLLOW_UPS = [
    (
        ["comprei 1 PETR4 hoje por 30"],
        "Xp no dia 9",
        Complement(data=date(2011, 3, 9), corretora="xp"),
    ),
    (["compra bova 11 hoje"], "PETR4", Complement(ativo="petr4")),
    (["comprei 10 PETR4 ontem"], "foi a 38,50", Complement(preco=Decimal("38.50"))),
]


def comparable(op: SpokenOp) -> tuple[object, ...]:
    return (
        op.tipo,
        normalize(op.ativo),
        op.quantidade.normalize() if op.quantidade is not None else None,
        op.preco.normalize() if op.preco is not None else None,
        op.moeda or "BRL" if op.preco is not None else op.moeda,
        op.data,
        normalize(op.corretora) if op.corretora else None,
    )


@pytest.fixture(scope="module")
def haiku():
    return AnthropicExtractor(
        os.environ["ANTHROPIC_API_KEY"],
        model=os.environ.get("CAURI_ANTHROPIC_MODEL", "claude-haiku-5-5"),
    )


@pytest.mark.parametrize("phrase", PHRASES)
def test_haiku_acerta_o_que_as_regras_acertam(haiku, phrase):
    expected = [comparable(op) for op in RuleExtractor().extract(phrase, TODAY).ops]
    got = [comparable(op) for op in haiku.extract(phrase, TODAY).ops]
    print(f"\n{phrase!r}\n  regras: {expected}\n  haiku:  {got}")
    assert got == expected


@pytest.mark.parametrize(("before", "phrase", "expected"), FOLLOW_UPS)
def test_seguimento_com_cartao_aberto_vira_complemento(haiku, before, phrase, expected):
    result = haiku.extract(phrase, TODAY, before)
    print(f"\n{before!r} -> {phrase!r}\n  haiku: {result.ops} {result.complement}")
    assert result.ops == ()
    got = result.complement
    assert got is not None
    assert (
        normalize(got.ativo or ""),
        got.preco,
        got.data,
        normalize(got.corretora or ""),
    ) == (
        normalize(expected.ativo or ""),
        expected.preco,
        expected.data,
        normalize(expected.corretora or ""),
    )


def test_operacao_nova_com_cartao_aberto_nao_e_complemento(haiku):
    result = haiku.extract("vendi 2 itau a 40", TODAY, ["comprei 1 PETR4 hoje por 30"])
    assert [op.tipo for op in result.ops] == ["venda"]
    assert result.complement is None


def test_quantidade_e_preco_chegam_como_decimal(haiku):
    [op] = haiku.extract("comprei 0,01 bitcoin a 120 mil dólares", TODAY).ops
    assert op.quantidade == Decimal("0.01")
    assert op.preco == Decimal(120000)
    assert isinstance(op.quantidade, Decimal)
