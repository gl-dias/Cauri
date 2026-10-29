"""Adaptadores da B3 (Negociação e Movimentação), sem banco."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from cauri_core import IncomeKind, MovementType
from cauri_importers import registry
from cauri_importers.adapters.b3 import B3MovimentacaoAdapter, B3NegociacaoAdapter
from cauri_importers.model import TesouroTitle, Ticker
from cauri_importers.privacy import looks_like_cpf
from cauri_importers.table import read

FIXTURES = Path(__file__).parent / "fixtures"


def parse(name: str):
    detected = read(name, (FIXTURES / name).read_bytes(), registry.ADAPTERS)
    return detected.adapter, detected.adapter.parse(detected.rows)


def test_negociacao_e_detectada_pelo_cabecalho_abaixo_da_identificacao():
    adapter, lines = parse("b3-negociacao.xlsx")
    assert isinstance(adapter, B3NegociacaoAdapter)
    # Cabeçalho na linha 4 (depois do bloco de identificação): a primeira negociação é a 5.
    assert lines[0].numbers == (5,)
    assert len(lines) == 8


def test_negociacao_vira_compras_e_vendas_com_o_fracionario_no_ticker_normal():
    _, lines = parse("b3-negociacao.xlsx")
    first, fractional, other_broker, _fii, sale, option, twin_a, twin_b = lines
    assert first.item.type is MovementType.COMPRA
    assert first.item.asset == Ticker("TSTA3")
    assert (first.item.quantity, first.item.unit_price) == (100, Decimal("20.0"))
    assert first.item.trade_date == date(2026, 1, 5)
    assert first.item.broker == "CORRETORA TESTE A"
    assert first.item.fees == 0  # a B3 não traz corretagem
    assert fractional.item.asset == Ticker("TSTA3")
    assert fractional.item.unit_price == Decimal("20.1")
    assert other_broker.item.broker == "CORRETORA TESTE B"
    assert sale.item.type is MovementType.VENDA
    assert option.item is None
    assert "opções" in option.ignored
    assert twin_a.item == twin_b.item  # duas compras iguais: o serviço numera a ocorrência


def test_movimentacao_ignora_a_liquidacao_reflexo_da_negociacao():
    adapter, lines = parse("b3-movimentacao.xlsx")
    assert isinstance(adapter, B3MovimentacaoAdapter)
    liquidation = lines[0]
    assert liquidation.item is None
    assert "export de Negociação" in liquidation.ignored


def test_movimentacao_proventos_tesouro_e_eventos():
    _, lines = parse("b3-movimentacao.xlsx")
    by_line = {line.numbers[0]: line for line in lines}
    rendimento = by_line[6].item
    assert rendimento.type is MovementType.PROVENTO
    assert rendimento.income_kind is IncomeKind.RENDIMENTO
    assert rendimento.amount == Decimal("8.5")
    assert by_line[7].item.income_kind is IncomeKind.DIVIDENDO
    assert by_line[8].item.income_kind is IncomeKind.JCP

    # O desdobro veio em duas linhas (uma por corretora) e vira um evento só.
    desdobro = by_line[9]
    assert desdobro.numbers == (9, 10)
    assert desdobro.item.type is MovementType.DESDOBRAMENTO
    assert desdobro.item.credited == 127
    assert 10 not in by_line

    tesouro = by_line[11].item
    assert tesouro.type is MovementType.COMPRA
    assert tesouro.asset == TesouroTitle("Tesouro Selic 2099")
    assert (tesouro.quantity, tesouro.unit_price) == (Decimal("0.5"), Decimal("15000.0"))

    bonus = by_line[12].item
    assert bonus.type is MovementType.BONIFICACAO
    assert (bonus.credited, bonus.unit_price) == (1, Decimal("95.0"))


def test_movimentacao_tipos_sem_efeito_ou_manuais_tem_motivo():
    _, lines = parse("b3-movimentacao.xlsx")
    by_line = {line.numbers[0]: line for line in lines}
    assert "custódia do Tesouro" in by_line[13].ignored
    assert "lance manualmente" in by_line[14].error  # Atualização
    assert "posição total não muda" in by_line[15].ignored  # Transferência
    assert "leilão" in by_line[16].ignored
    assert "ainda não reconhecido: Cisão" in by_line[17].error


def test_identificacao_do_investidor_nunca_e_carregada():
    for name in ("b3-negociacao.xlsx", "b3-movimentacao.xlsx"):
        _, lines = parse(name)
        for line in lines:
            text = " ".join(line.raw.values())
            assert "Fulano" not in text
            assert not looks_like_cpf(text)


def test_template_generico_nao_e_confundido_com_a_b3():
    detected = read(
        "x.csv",
        b"data;tipo;ativo;classe;corretora\n01/02/2026;compra;TSTA3;acao;X\n",
        registry.ADAPTERS,
    )
    assert detected.adapter.name == "planilha"


def test_avisos_do_envio_dependem_dos_arquivos():
    only_mov = registry.batch_warnings(["b3-movimentacao"])
    assert any("Negociação" in w for w in only_mov)
    both = registry.batch_warnings(["b3-movimentacao", "b3-negociacao"])
    assert not any("envie também" in w for w in both)
    assert any("corretagem" in w for w in both)
    assert registry.batch_warnings(["planilha"]) == []
