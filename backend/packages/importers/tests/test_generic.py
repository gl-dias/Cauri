"""Leitor de planilha e template genérico, sem banco."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cauri_core import IncomeKind, MovementType
from cauri_importers import registry
from cauri_importers.adapters.generic import GenericAdapter
from cauri_importers.model import PrivateFixedIncome, TesouroTitle, Ticker
from cauri_importers.privacy import looks_like_cpf
from cauri_importers.table import FileError, read

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE = Path(__file__).parents[4] / "reference" / "import-template"


def parse(name: str, folder: Path = FIXTURES):
    detected = read(name, (folder / name).read_bytes(), registry.ADAPTERS)
    return detected.adapter, detected.adapter.parse(detected.rows)


@pytest.mark.parametrize("name", ["cauri-importacao.csv", "cauri-importacao.xlsx"])
def test_template_publicado_e_lido_inteiro_sem_erro(name):
    adapter, lines = parse(name, TEMPLATE)
    assert isinstance(adapter, GenericAdapter)
    assert [line.error for line in lines] == [None] * 8
    items = [line.item for line in lines]
    assert all(items)
    compra, _fii, provento, tesouro, cdb, btc, venda, desdobro = items
    assert compra.type is MovementType.COMPRA
    assert compra.asset == Ticker("PETR4")
    assert (compra.quantity, compra.unit_price, compra.fees) == (
        100,
        Decimal("36.80"),
        Decimal("4.90"),
    )
    assert compra.trade_date == date(2025, 3, 10)
    assert provento.income_kind is IncomeKind.RENDIMENTO
    assert provento.amount == Decimal("22.00")
    assert tesouro.asset == TesouroTitle("Tesouro Selic 2029")
    assert tesouro.unit_price == Decimal("15120.44")
    assert isinstance(cdb.asset, PrivateFixedIncome)
    assert cdb.asset.terms.rate_pct == 110
    assert cdb.asset.terms.maturity_date == date(2028, 5, 5)
    assert cdb.amount == Decimal("5000.00")
    assert btc.quantity == Decimal("0.0025")
    assert venda.notes == "venda parcial"
    assert desdobro.factor == 2


def test_csv_e_xlsx_do_template_dao_o_mesmo_resultado():
    _, from_csv = parse("cauri-importacao.csv", TEMPLATE)
    _, from_xlsx = parse("cauri-importacao.xlsx", TEMPLATE)
    assert [line.item for line in from_csv] == [line.item for line in from_xlsx]


def test_linhas_com_problema_viram_erro_com_mensagem_e_o_resto_segue():
    _, lines = parse("generico.csv")
    assert [line.numbers[0] for line in lines] == [2, 3, 4, 5, 6, 7, 8]
    assert lines[0].error is None
    assert lines[2].error is None
    assert "Data inválida" in lines[3].error
    assert "Tipo desconhecido: troca" in lines[4].error
    # Corretora desconhecida só é decidida contra o cadastro, no serviço.
    assert lines[5].error is None
    assert lines[5].item.broker == "Corretora Que Nao Existe"


def test_cpf_em_texto_livre_e_mascarado_antes_de_sair_do_parser():
    _, lines = parse("generico.csv")
    obs = lines[6]
    assert obs.item.notes == "contato ***"
    assert obs.raw["obs"] == "contato ***"


def test_xlsx_com_folha_de_rosto_e_coluna_de_cpf_nunca_carrega_dado_pessoal():
    adapter, lines = parse("generico.xlsx")
    assert isinstance(adapter, GenericAdapter)
    assert len(lines) == 8
    for line in lines:
        assert "cpf" not in line.raw
        assert not any(looks_like_cpf(v) for v in line.raw.values())
        assert "Fulano" not in str(line.raw)
    # O cabeçalho estava na linha 4 da segunda folha.
    assert lines[0].numbers == (5,)


def test_formato_desconhecido_e_arquivos_invalidos_tem_mensagem_clara():
    with pytest.raises(FileError, match="Não reconheci"):
        read("x.csv", b"a;b;c\n1;2;3\n", registry.ADAPTERS)
    with pytest.raises(FileError, match=r"\.xls antigo"):
        read("x.xls", b"qualquer", registry.ADAPTERS)
    with pytest.raises(FileError, match="corrompido"):
        read("x.xlsx", b"isto nao e zip", registry.ADAPTERS)
    with pytest.raises(FileError, match="vazio"):
        read("x.csv", b"", registry.ADAPTERS)
    with pytest.raises(FileError, match="Formato não suportado"):
        read("x.pdf", b"%PDF", registry.ADAPTERS)


def test_csv_com_virgula_e_numeros_com_ponto_decimal():
    content = (
        b"data,tipo,ativo,classe,quantidade,preco,corretora\n"
        b"02/01/2025,compra,BTC,cripto,0.001,350000.50,Binance\n"
    )
    detected = read("x.csv", content, registry.ADAPTERS)
    [line] = detected.adapter.parse(detected.rows)
    assert line.item.quantity == Decimal("0.001")
    assert line.item.unit_price == Decimal("350000.50")


def test_csv_em_latin1_do_excel_brasileiro():
    content = (
        "data;tipo;ativo;classe;valor;corretora;obs\n"
        "15/04/2025;provento;HGLG11;fii;10,00;BTG Pactual;rendimento março\n"
    )
    detected = read("x.csv", content.encode("cp1252"), registry.ADAPTERS)
    [line] = detected.adapter.parse(detected.rows)
    assert line.item.notes == "rendimento março"
