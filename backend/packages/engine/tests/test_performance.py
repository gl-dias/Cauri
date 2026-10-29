from datetime import date
from decimal import Decimal

from cauri_engine.calc import (
    CdiCurve,
    cdi_index,
    daily_return,
    ipca_index,
    next_quota,
    period_return,
)
from engine_factories import D


def test_retorno_do_dia_sem_fluxo():
    assert daily_return(D(1000), D(1100), D(0), D(0)) == D("0.1")


def test_aporte_no_meio_do_periodo_nao_distorce_a_rentabilidade():
    # Dia 1: compra 1000, fecha em 1000. Dia 2: sobe 10%. Dia 3: aporta 1000 e o dia sobe 5%.
    q = next_quota(D(1), D(0), D(1000), inflow=D(1000), outflow=D(0))
    assert q == 1
    q = next_quota(q, D(1000), D(1100), D(0), D(0))
    assert q == D("1.1")
    q = next_quota(q, D(1100), D(2205), inflow=D(1000), outflow=D(0))
    assert q == D("1.155")  # 1,10 x 1,05: o aporte não vira "rentabilidade"


def test_ganho_entre_preco_de_compra_e_fechamento_aparece_no_dia():
    q = next_quota(D(1), D(0), D(1050), inflow=D(1000), outflow=D(0))
    assert q == D("1.05")


def test_provento_conta_como_retorno():
    q = next_quota(D(1), D(1000), D(1000), inflow=D(0), outflow=D(10))
    assert q == D("1.01")


def test_vender_tudo_e_recomprar_mantem_a_cota_continua():
    q = next_quota(
        D("1.2"), D(1000), D(0), inflow=D(0), outflow=D(1000)
    )  # vendeu tudo no fechamento
    assert q == D("1.2")
    q = next_quota(q, D(0), D(0), D(0), D(0))  # dia sem nada investido
    assert q == D("1.2")
    q = next_quota(q, D(0), D(550), inflow=D(500), outflow=D(0))  # recomprou e subiu 10%
    assert q == D("1.32")


def test_rentabilidade_do_periodo_pela_cota():
    assert period_return(D("1.10"), D("1.155")) == D("0.05")


def test_cdi_acumulado_usa_a_mesma_convencao_da_renda_fixa():
    rates = {date(2026, 3, 2): D("0.05"), date(2026, 3, 3): D("0.05")}
    curve = CdiCurve(rates)
    assert cdi_index(curve, date(2026, 3, 2), date(2026, 3, 2)) == 1
    assert cdi_index(curve, date(2026, 3, 2), date(2026, 3, 4)) == D("1.0005") * D("1.0005")


class TestIpca:
    MONTHLY = {date(2026, 1, 1): D("0.50"), date(2026, 2, 1): D("0.40")}

    def test_mes_entra_quando_acaba(self):
        assert ipca_index(self.MONTHLY, date(2026, 1, 1), date(2026, 1, 31)) == 1
        assert ipca_index(self.MONTHLY, date(2026, 1, 1), date(2026, 2, 15)) == D("1.005")
        assert ipca_index(self.MONTHLY, date(2026, 1, 1), date(2026, 3, 15)) == D("1.005") * D(
            "1.004"
        )

    def test_mes_nao_publicado_interrompe_sem_estimar(self):
        assert ipca_index(self.MONTHLY, date(2026, 1, 1), date(2026, 5, 10)) == D("1.005") * D(
            "1.004"
        )

    def test_mes_de_inicio_entra_proporcional(self):
        index = ipca_index(self.MONTHLY, date(2026, 1, 17), date(2026, 2, 2))
        expected = D("1.005") ** (Decimal(15) / Decimal(31))  # 17 a 31 de janeiro
        assert index == expected
