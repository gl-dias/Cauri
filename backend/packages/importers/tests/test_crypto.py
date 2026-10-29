"""Cripto (Binance e template), perfis de colunas e conversão para reais, sem banco."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from cauri_core import IncomeKind, MovementType
from cauri_importers import fx, registry
from cauri_importers.adapters.binance import split_pair
from cauri_importers.adapters.crypto import CryptoTemplateAdapter
from cauri_importers.adapters.mapped import MappedAdapter
from cauri_importers.model import Item, Ticker
from cauri_importers.table import UnknownFormatError, read
from cauri_ledger import ImportProfile

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE = Path(__file__).parents[4] / "reference" / "import-template"


def parse(name: str, folder: Path = FIXTURES, adapters=registry.ADAPTERS):
    detected = read(name, (folder / name).read_bytes(), adapters)
    return detected.adapter, detected.adapter.parse(detected.rows)


def legs(lines, number):
    return [line for line in lines if line.numbers[0] == number]


class TestBinanceTrades:
    def test_compra_com_taxa_na_propria_moeda_vira_compra_e_pagamento_em_usdt(self):
        adapter, lines = parse("binance-trades.csv")
        assert adapter.name == "binance-trades"
        buy, paid = legs(lines, 2)
        assert buy.item.type is MovementType.COMPRA
        assert buy.item.asset == Ticker("TSTCOIN")
        # Taxa em TSTCOIN sai das moedas recebidas e entra como custo, na cotação.
        assert buy.item.quantity == Decimal("0.4995")
        assert (buy.item.unit_price, buy.item.currency) == (Decimal("200.00"), "USDT")
        assert buy.item.fees == Decimal("0.1")
        assert buy.item.fee_paid == ("TSTCOIN", Decimal("0.0005"))
        assert paid.item.type is MovementType.VENDA
        assert (paid.item.asset, paid.item.quantity) == (Ticker("USDT"), Decimal("100"))
        assert (paid.item.unit_price, paid.item.currency) == (1, "USDT")
        assert "Contrapartida" in paid.notes[0]

    def test_taxa_em_terceiro_ativo_vira_custo_e_venda_desse_ativo(self):
        _, lines = parse("binance-trades.csv")
        buy, _paid, fee = legs(lines, 3)
        assert (buy.item.fee_asset, buy.item.fee_quantity) == ("TSTFEE", Decimal("0.1"))
        assert buy.item.fees == 0
        assert fee.item.type is MovementType.VENDA
        assert (fee.item.asset, fee.item.quantity, fee.item.currency) == (
            Ticker("TSTFEE"),
            Decimal("0.1"),
            "TSTFEE",
        )

    def test_venda_com_taxa_na_cotacao_recebe_o_total_menos_a_taxa(self):
        _, lines = parse("binance-trades.csv")
        sale, received = legs(lines, 4)
        assert sale.item.type is MovementType.VENDA
        assert sale.item.fees == Decimal("0.021")
        assert received.item.type is MovementType.COMPRA
        assert received.item.quantity == Decimal("20.979")

    def test_par_em_reais_nao_tem_contrapartida_e_a_data_e_a_de_brasilia(self):
        _, lines = parse("binance-trades.csv")
        [buy] = legs(lines, 5)
        # 04/03 01:30 UTC ainda é 03/03 em Brasília.
        assert buy.item.trade_date == date(2011, 3, 3)
        assert buy.item.currency == "BRL"

    def test_par_cotado_em_outra_cripto(self):
        _, lines = parse("binance-trades.csv")
        buy, paid = legs(lines, 6)
        assert buy.item.currency == "TSTCOIN"
        assert buy.item.quantity == Decimal("9.99")
        assert paid.item.asset == Ticker("TSTCOIN")

    def test_layout_antigo_da_o_mesmo_resultado(self):
        adapter, old = parse("binance-trades-antigo.csv")
        assert adapter.name == "binance-trades-antigo"
        _, new = parse("binance-trades.csv")
        assert [line.item for line in old] == [line.item for line in legs(new, 2)]
        assert len(old) == 2

    def test_par_sem_separador(self):
        assert split_pair("BTCUSDT") == ("BTC", "USDT")
        assert split_pair("ETHFDUSD") == ("ETH", "FDUSD")
        assert split_pair("ETH/BTC") == ("ETH", "BTC")


class TestBinanceOutros:
    def test_convert_vira_compra_e_venda_e_o_que_falhou_e_ignorado(self):
        adapter, lines = parse("binance-convert.csv")
        assert adapter.name == "binance-convert"
        buy, sold, failed = lines
        assert (buy.item.asset, buy.item.quantity) == (Ticker("TSTCOIN"), Decimal("0.2"))
        assert (buy.item.unit_price, buy.item.currency) == (Decimal("200"), "USDT")
        assert (sold.item.asset, sold.item.quantity) == (Ticker("USDT"), Decimal("40"))
        assert failed.ignored == "Conversão não concluída."

    def test_depositos_sao_custodia_ou_dinheiro(self):
        adapter, lines = parse("binance-depositos.csv")
        assert adapter.name == "binance-transferencias"
        fiat, coin = lines
        assert "dinheiro em conta" in fiat.ignored
        assert "custódia" in coin.ignored
        assert all("TXID" not in line.raw and "id-ficticio" not in str(line.raw) for line in lines)

    def test_extrato_traz_recompensas_e_ignora_o_que_vem_dos_trades(self):
        adapter, lines = parse("binance-extrato.csv")
        assert adapter.name == "binance-extrato"
        income, bought = legs(lines, 2)
        assert income.item.type is MovementType.PROVENTO
        assert income.item.income_kind is IncomeKind.RENDIMENTO
        assert (income.item.amount, income.item.currency) == (Decimal("0.01"), "TSTCOIN")
        assert bought.item.type is MovementType.COMPRA
        assert legs(lines, 3)[0].ignored.startswith("Compra, venda ou taxa")
        assert "dinheiro em conta" in legs(lines, 4)[0].ignored
        assert "carteiras da própria Binance" in legs(lines, 5)[0].ignored
        assert "export de P2P" in legs(lines, 6)[0].ignored
        assert "não reconhecida: Mystery Box" in legs(lines, 7)[0].error

    def test_extrato_nunca_le_id_de_usuario_nem_observacao(self):
        _, lines = parse("binance-extrato.csv")
        for line in lines:
            assert "98765432" not in str(line.raw)
            assert "Fulano" not in str(line.raw)

    def test_aviso_quando_vem_o_extrato_sem_os_trades(self):
        assert any("trades" in w for w in registry.batch_warnings(["binance-extrato"]))
        assert not any(
            "trades" in w for w in registry.batch_warnings(["binance-extrato", "binance-trades"])
        )


class TestTemplateCripto:
    @pytest.mark.parametrize("name", ["cauri-cripto.csv", "cauri-cripto.xlsx"])
    def test_template_publicado_e_lido_sem_erro(self, name):
        adapter, lines = parse(name, TEMPLATE)
        assert isinstance(adapter, CryptoTemplateAdapter)
        assert [line.error for line in lines] == [None] * len(lines)
        # BRL: 1 linha; USDT com taxa em BNB: 3; recompensa: 2; USD: 1.
        assert len(lines) == 7

    def test_fixture(self):
        _, lines = parse("cripto.csv")
        buy, paid, fee = legs(lines, 2)
        assert (buy.item.fee_asset, buy.item.fee_quantity) == ("TSTFEE", Decimal("0.1"))
        assert paid.item.asset == Ticker("USDT")
        assert fee.item.asset == Ticker("TSTFEE")
        [sale] = legs(lines, 3)
        assert (sale.item.currency, sale.item.fees) == ("BRL", Decimal("1.00"))
        income, _received = legs(lines, 4)
        assert income.item.type is MovementType.PROVENTO


def profile(**mapping_overrides):
    mapping = {
        "data": "Data Operação",
        "tipo": "Operação",
        "ativo": "Papel",
        "quantidade": "Qtde",
        "preco": "Preço",
        "valor": "Valor Total",
        "taxa": "Corretagem",
    } | mapping_overrides
    return ImportProfile(
        id=uuid4(),
        name="Corretora Fictícia",
        mapping=mapping,
        options={"broker_id": "corretora-teste-a", "decimal": ",", "date_format": "dd/mm/aaaa"},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        last_used_at=None,
    )


class TestPerfil:
    def test_arquivo_desconhecido_devolve_so_os_nomes_das_colunas(self):
        name = "corretora-desconhecida.csv"
        with pytest.raises(UnknownFormatError) as exc:
            read(name, (FIXTURES / name).read_bytes(), registry.ADAPTERS)
        assert exc.value.columns == [
            "Data Operação", "Operação", "Papel", "Qtde", "Preço", "Valor Total", "Corretagem",
        ]  # fmt: skip

    def test_perfil_salvo_reconhece_e_le_o_arquivo(self):
        p = profile()
        adapter, lines = parse("corretora-desconhecida.csv", adapters=registry.adapters_for([p]))
        assert isinstance(adapter, MappedAdapter)
        assert adapter.label == "Corretora Fictícia"
        buy, sale, income = lines
        assert buy.item.type is MovementType.COMPRA
        assert (buy.item.quantity, buy.item.unit_price, buy.item.fees) == (10, 20, 1)
        assert buy.item.broker == "corretora-teste-a"
        assert sale.item.type is MovementType.VENDA
        assert income.item.type is MovementType.PROVENTO
        assert income.item.amount == 3

    def test_perfil_exige_todas_as_colunas_mapeadas(self):
        p = profile(obs="Observações")  # coluna que o arquivo não tem
        with pytest.raises(UnknownFormatError):
            parse("corretora-desconhecida.csv", adapters=registry.adapters_for([p]))


class TestConversao:
    ptax = {date(2011, 3, 3): Decimal("1.6600"), date(2011, 3, 4): Decimal("1.6650")}
    closes = {"TSTFEE": {date(2011, 3, 5): Decimal("2.5")}}

    def item(self, **kw):
        base = {
            "trade_date": date(2011, 3, 4),
            "type": MovementType.COMPRA,
            "asset": Ticker("TSTCOIN"),
            "broker": "binance",
            "quantity": Decimal("0.5"),
            "unit_price": Decimal("200"),
        }
        return Item(**(base | kw))

    def test_usdt_pela_ptax_do_dia(self):
        book = fx.RateBook(self.ptax, self.closes)
        conv = fx.convert(
            self.item(currency="USDT", fees=Decimal("0.1"), fee_paid=("USDT", Decimal("0.1"))),
            book,
        )
        assert conv.item.unit_price == Decimal("333.0000000000")
        assert conv.item.fees == Decimal("0.17")
        assert (conv.rate.value, conv.rate.on, conv.rate.source) == (
            Decimal("1.6650"),
            date(2011, 3, 4),
            "ptax",
        )
        assert (conv.fee_asset, conv.fee_quantity) == ("USDT", Decimal("0.1"))
        assert "última antes" not in conv.notes[0]

    def test_fim_de_semana_usa_a_ultima_ptax_e_avisa(self):
        book = fx.RateBook(self.ptax, self.closes)
        conv = fx.convert(self.item(trade_date=date(2011, 3, 5), currency="USDT"), book)
        assert conv.rate.on == date(2011, 3, 4)
        assert "04/03/2011" in conv.notes[0]
        assert "última antes da data da operação" in conv.notes[0]

    def test_taxa_em_outro_ativo_pelo_fechamento(self):
        book = fx.RateBook(self.ptax, self.closes)
        conv = fx.convert(
            self.item(
                trade_date=date(2011, 3, 5),
                fee_asset="TSTFEE",
                fee_quantity=Decimal("0.1"),
            ),
            book,
        )
        assert conv.item.fees == Decimal("0.25")
        assert "fechamento do TSTFEE" in conv.notes[0]

    def test_sem_cotacao_e_erro_claro(self):
        book = fx.RateBook({}, {})
        with pytest.raises(fx.ConversionError, match="Sem PTAX"):
            fx.convert(self.item(currency="USDT"), book)
        with pytest.raises(fx.ConversionError, match="Sem fechamento"):
            fx.convert(self.item(currency="TSTFEE"), book)


class TestP2PeDepositos:
    def test_p2p_vira_compra_e_venda_com_real_sem_contrapartida(self):
        adapter, lines = parse("binance-p2p.csv")
        assert adapter.name == "binance-p2p"
        buy, sell, cancelled = lines
        assert buy.item.type is MovementType.COMPRA
        assert (buy.item.asset, buy.item.quantity) == (Ticker("USDT"), Decimal("150"))
        assert (buy.item.unit_price, buy.item.currency) == (Decimal("1.655"), "BRL")
        assert sell.item.type is MovementType.VENDA
        assert cancelled.ignored == "Ordem P2P não concluída."
        for line in lines:
            assert "ficticio" not in str(line.raw)  # apelido da contraparte nunca é lido
            assert "20110301000001" not in str(line.raw)  # nem o número da ordem

    def test_deposito_de_cripto_leva_moeda_quantidade_e_dia(self):
        _, lines = parse("binance-deposito-usdt.csv")
        [deposit] = lines
        assert deposit.item is None
        assert deposit.transfer.kind == "deposito"
        assert (deposit.transfer.coin, deposit.transfer.quantity) == ("USDT", Decimal("150"))
        assert deposit.transfer.day == date(2011, 3, 1)
        _, fiat = parse("binance-depositos.csv")
        assert fiat[0].transfer is None  # depósito em real não explica saldo de cripto

    def test_saldo_inicial_nos_templates(self):
        detected = read(
            "x.csv",
            b"data;tipo;ativo;classe;quantidade;preco;corretora\n"
            b"01/01/2026;saldo_inicial;TSTA3;acao;100;18,50;Corretora Teste A\n",
            registry.ADAPTERS,
        )
        [line] = detected.adapter.parse(detected.rows)
        assert line.item.type is MovementType.COMPRA
        assert line.item.opening_balance
