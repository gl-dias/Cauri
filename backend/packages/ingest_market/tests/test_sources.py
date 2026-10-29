"""Parsers das fontes de mercado, com amostras reais das respostas (sem rede)."""

import zipfile
from datetime import date
from decimal import Decimal

import pytest

from cauri_ingest_market.reference import normalize_alias, sync_aliases
from cauri_ingest_market.sources import bcb_sgs, coingecko, cotahist, tesouro

# Linhas reais do COTAHIST_A2026 (05/01/2026).
PETR4 = (
    "012026010502PETR4       010PETROBRAS   PN  EDJ N2   R$  "
    "000000000307000000000030770000000002973"
    "000000000300800000000030200000000003020000000000302152803000000000048211400000000145060421200"
    "000000000000009999123100000010000000000000BRPETRACNPR6223"
)
HGLG11 = (
    "012026010512HGLG11      010FII HGLG PAXCI  ER       R$  "
    "000000001580700000000158100000000015699"
    "000000001572800000000157350000000015735000000001575623960000000000000094297000000001483161587"
    "000000000000009999123100000010000000000000BRHGLGCTF004291"
)
HEADER = "00COTAHIST.2026BOVESPA 20261028".ljust(245)


class TestCotahist:
    def test_le_acao_do_mercado_a_vista(self):
        quote = cotahist.parse_line(PETR4)
        assert quote is not None
        assert quote.ticker == "PETR4"
        assert quote.trade_date == date(2026, 1, 5)
        assert quote.close == Decimal("30.20")
        assert quote.short_name == "PETROBRAS"
        assert quote.spec == "PN EDJ N2"
        assert quote.isin == "BRPETRACNPR6"

    def test_le_fii(self):
        quote = cotahist.parse_line(HGLG11)
        assert quote is not None
        assert quote.bdi == cotahist.BDI_REITS
        assert quote.close == Decimal("157.35")

    def test_ignora_cabecalho_e_outros_mercados(self):
        assert cotahist.parse_line(HEADER) is None
        fracionario = PETR4[:24] + "020" + PETR4[27:]
        assert cotahist.parse_line(fracionario) is None
        bdr = PETR4[:10] + "34" + PETR4[12:]
        assert cotahist.parse_line(bdr) is None

    def test_fator_de_cotacao_divide_o_preco(self):
        por_mil = PETR4[:210] + "0001000" + PETR4[217:]
        quote = cotahist.parse_line(por_mil)
        assert quote is not None
        assert quote.close == Decimal("0.0302")

    def test_le_do_zip_filtrando_tickers(self, tmp_path):
        path = tmp_path / "COTAHIST_A2026.ZIP"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("COTAHIST_A2026.TXT", "\r\n".join([HEADER, PETR4, HGLG11]).encode("latin-1"))
        assert [q.ticker for q in cotahist.iter_quotes(path)] == ["PETR4", "HGLG11"]
        assert [q.ticker for q in cotahist.iter_quotes(path, {"hglg11"})] == ["HGLG11"]


TESOURO_HEADER = (
    "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
    "PU Compra Manha;PU Venda Manha;PU Base Manha"
)
TESOURO_CSV = (
    TESOURO_HEADER
    + """
Tesouro Selic;01/03/2028;27/10/2026;0,02;0,03;20175,28;20162,27;20162,27
Tesouro IPCA+;15/05/2035;27/10/2026;7,10;7,22;2210,01;2191,45;2191,45
Tesouro IPCA+ com Juros Semestrais;15/08/2060;27/10/2026;;7,05;;4012,34;4012,34
Tesouro Prefixado;01/01/2024;28/12/2023;0,00;0,00;0,00;0,00;0,00
"""
)


class TestTesouro:
    def test_le_o_csv_oficial(self):
        rows = list(tesouro.parse(TESOURO_CSV))
        assert len(rows) == 3  # PU zero (título vencido) fica de fora
        selic = rows[0]
        assert selic.maturity == date(2028, 3, 1)
        assert selic.base_date == date(2026, 10, 27)
        assert selic.pu_base == Decimal("20162.27")
        assert rows[2].pu_buy is None  # sem venda ao investidor nesse dia

    def test_ticker_e_nome_interno(self):
        assert tesouro.ticker_for("Tesouro IPCA+", date(2035, 5, 15)) == "TD-IPCA-15052035"
        assert (
            tesouro.ticker_for("Tesouro IPCA+ com Juros Semestrais", date(2060, 8, 15))
            == "TD-IPCA-JS-15082060"
        )
        assert tesouro.ticker_for("Título que não existe", date(2030, 1, 1)) is None
        assert (
            tesouro.name_for("Tesouro Selic", date(2028, 3, 1)) == "Tesouro Selic 2028 (01/03/2028)"
        )

    def test_cabecalho_errado_e_recusado(self):
        with pytest.raises(ValueError, match="cabeçalho"):
            list(tesouro.parse("a;b;c\n1;2;3\n"))


def test_sgs_le_data_e_valor_sem_float():
    points = bcb_sgs.parse(
        [{"data": "27/10/2026", "valor": "0.050788"}, {"data": "01/09/2026", "valor": "0.82"}]
    )
    assert points == [
        (date(2026, 10, 27), Decimal("0.050788")),
        (date(2026, 9, 1), Decimal("0.82")),
    ]


def test_series_do_bcb_corretas():
    assert (
        bcb_sgs.CDI.code,
        bcb_sgs.SELIC_META.code,
        bcb_sgs.SELIC_EFETIVA.code,
        bcb_sgs.IPCA.code,
    ) == (
        12,
        432,
        1178,
        433,
    )


def test_coingecko_ponto_das_00h_utc_vira_fechamento_do_dia_anterior_em_brasilia():
    # 2026-10-28T00:00:00Z = 27/10/2026 21:00 em Brasília
    payload = {"prices": [[1793145600000, 426534.12], [1793232000000, 430001.5]]}
    points = coingecko.parse_history(payload)
    assert points == [
        (date(2026, 10, 27), Decimal("426534.12")),
        (date(2026, 10, 28), Decimal("430001.5")),
    ]


class TestApelidos:
    def test_normaliza_acento_caixa_e_espacos(self):
        assert normalize_alias("  Itaú   Unibanco ") == "itau unibanco"
        assert normalize_alias("ITAÚSA") == "itausa"

    def test_mesmo_apelido_para_empresas_diferentes_e_erro(self):
        with pytest.raises(ValueError, match="aponta para ITUB e ITSA"):
            sync_aliases(None, {"ITUB": ["Itaú"], "ITSA": ["itau"]}, {})  # type: ignore[arg-type]
