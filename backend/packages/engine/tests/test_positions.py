from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cauri_core import MovementType
from cauri_engine.calc import AssetBook, OversellError, find_oversell, replay
from engine_factories import ASSET_A, ASSET_B, D, buy, event, income, sell

JAN = date(2026, 1, 5)


def book_of(*movements):
    return replay(movements)[ASSET_A]


class TestPrecoMedio:
    def test_preco_medio_ponderado_inclui_as_taxas_da_compra(self):
        book = book_of(buy(JAN, 100, 10, fees=5), buy(date(2026, 1, 6), 50, 13, fees=5))
        assert book.quantity == 150
        assert book.cost_basis == D("1660")  # 1005 + 655
        assert book.avg_cost == D(1660) / D(150)

    def test_venda_parcial_nao_altera_o_preco_medio_e_realiza_contra_ele(self):
        book = book_of(
            buy(JAN, 100, 10, fees=5),
            buy(date(2026, 1, 6), 50, 13, fees=5),
            sell(date(2026, 1, 7), 60, 15, fees="4.50"),
        )
        assert book.quantity == 90
        assert book.cost_basis == D("996")  # 1660 * 90/150
        assert book.avg_cost == D(1660) / D(150)
        # (60 x 15 - 4,50) - 60 x PM = 895,50 - 664
        assert book.realized_pnl == D("231.50")

    def test_vendas_parciais_seguidas_somam_o_resultado(self):
        book = book_of(
            buy(JAN, 100, 10),
            sell(date(2026, 1, 6), 30, 12),
            sell(date(2026, 1, 7), 30, 8),
        )
        assert book.quantity == 40
        assert book.realized_pnl == D("60") + D("-60")
        assert book.avg_cost == D(10)

    def test_venda_total_zera_custo_sem_residuo(self):
        book = book_of(buy(JAN, 3, "33.33", fees="0.01"), sell(date(2026, 1, 6), 3, 40))
        assert book.quantity == 0
        assert book.cost_basis == 0
        assert book.avg_cost is None
        assert book.realized_pnl == D("120") - D("100.00")

    def test_recompra_depois_de_zerar_comeca_preco_medio_novo(self):
        book = book_of(
            buy(JAN, 10, 10),
            sell(date(2026, 1, 6), 10, 12),
            buy(date(2026, 1, 7), 10, 20),
        )
        assert book.avg_cost == D(20)
        assert book.realized_pnl == D(20)

    def test_compra_e_venda_no_mesmo_dia_compra_conta_primeiro(self):
        # A venda foi lançada antes, mas no mesmo dia a compra entra primeiro.
        book = book_of(sell(JAN, 5, 11), buy(JAN, 5, 10))
        assert book.quantity == 0
        assert book.realized_pnl == D(5)


class TestEventosCorporativos:
    def test_desdobramento_dobra_quantidade_e_divide_preco_medio(self):
        book = book_of(buy(JAN, 100, 10), event(date(2026, 2, 1), MovementType.DESDOBRAMENTO, "2"))
        assert book.quantity == 200
        assert book.cost_basis == 1000
        assert book.avg_cost == 5

    def test_grupamento_reduz_quantidade_e_multiplica_preco_medio(self):
        book = book_of(buy(JAN, 100, 1), event(date(2026, 2, 1), MovementType.GRUPAMENTO, "0.1"))
        assert book.quantity == 10
        assert book.avg_cost == 10

    def test_bonificacao_soma_acoes_com_custo_atribuido(self):
        book = book_of(
            buy(JAN, 100, 10),
            event(date(2026, 2, 1), MovementType.BONIFICACAO, "0.1", unit_cost="8"),
        )
        assert book.quantity == 110
        assert book.cost_basis == D(1080)
        assert book.avg_cost == D(1080) / D(110)

    def test_evento_na_data_ex_vale_antes_das_negociacoes_do_dia(self):
        # Desdobramento e compra no mesmo dia: a compra já é em quantidade nova.
        book = book_of(
            buy(JAN, 10, 10),
            buy(date(2026, 2, 1), 10, 5),
            event(date(2026, 2, 1), MovementType.DESDOBRAMENTO, "2"),
        )
        assert book.quantity == 30


class TestVendaDescoberta:
    def test_venda_maior_que_a_posicao_e_recusada(self):
        with pytest.raises(OversellError) as exc:
            book_of(buy(JAN, 10, 10), sell(date(2026, 1, 6), 11, 10))
        assert exc.value.shortfall == 1
        assert exc.value.available == 10

    def test_venda_retroativa_antes_da_compra_e_encontrada(self):
        found = find_oversell([buy(date(2026, 1, 10), 10, 10), sell(JAN, 5, 10)])
        assert found is not None
        assert found.trade_date == JAN
        assert found.shortfall == 5

    def test_remover_compra_que_cobria_venda_posterior_descobre_a_venda(self):
        compra_antiga = buy(JAN, 10, 10)
        movements = [compra_antiga, buy(date(2026, 1, 6), 5, 10), sell(date(2026, 1, 7), 12, 11)]
        assert find_oversell(movements) is None
        assert find_oversell([m for m in movements if m is not compra_antiga]) is not None

    def test_ativos_diferentes_nao_se_compensam(self):
        found = find_oversell([buy(JAN, 10, 10, asset=ASSET_A), sell(JAN, 1, 10, asset=ASSET_B)])
        assert found is not None
        assert found.asset_id == ASSET_B


def test_quantidade_e_resultado_por_corretora():
    book = book_of(
        buy(JAN, 10, 10, broker="a"),
        buy(JAN, 20, 13, broker="b"),
        sell(date(2026, 1, 6), 5, 14, broker="b"),
        income(date(2026, 1, 7), "3.00", broker="a"),
    )
    assert book.quantity_by_broker == {"a": 10, "b": 15}
    assert book.income_by_broker["a"] == D(3)
    # PM consolidado: 360/30 = 12; a venda na b realiza contra ele: 5 x 14 - 5 x 12.
    assert book.realized_by_broker["b"] == D(10)


@given(
    st.lists(
        st.tuples(
            st.booleans(),
            st.integers(min_value=1, max_value=500),
            st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999"), places=2),
            st.decimals(min_value=Decimal(0), max_value=Decimal("20"), places=2),
        ),
        min_size=1,
        max_size=40,
    )
)
def test_propriedade_venda_nunca_muda_preco_medio_e_custo_fecha_a_conta(ops):
    book = AssetBook()
    bought_cost = Decimal(0)
    removed_cost = Decimal(0)
    day = JAN
    for is_buy, qty, price, fees in ops:
        if is_buy or book.quantity == 0:
            book.apply(buy(day, qty, price, fees=fees))
            bought_cost += qty * price + fees
        else:
            qty_to_sell = min(Decimal(qty), book.quantity)
            avg_before = book.avg_cost
            cost_before = book.cost_basis
            book.apply(sell(day, qty_to_sell, price, fees=fees))
            removed_cost += cost_before - book.cost_basis
            if book.quantity > 0:
                assert avg_before is not None
                assert book.avg_cost is not None
                assert abs(book.avg_cost - avg_before) < Decimal("1e-20")
        assert book.cost_basis >= 0
        assert book.quantity >= 0
    assert abs(bought_cost - removed_cost - book.cost_basis) < Decimal("1e-18")
