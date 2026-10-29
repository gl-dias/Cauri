from datetime import date, timedelta
from decimal import Decimal

import pytest

from cauri_core import FiKind, FixedIncomeTerms
from cauri_core.calendar import b3_trading_days
from cauri_core.money import trunc
from cauri_engine.calc import CdiCurve, FixedIncomeBook, RedemptionExceedsBalanceError, daily_factor
from engine_factories import INSTRUMENT, D, deposit, redeem

CDI = D("0.050788")  # % a.d. (13,65% a.a. aprox.)


def terms(rate_pct: str = "100", maturity: date = date(2030, 1, 2)) -> FixedIncomeTerms:
    return FixedIncomeTerms(
        id=INSTRUMENT,
        kind=FiKind.CDB,
        issuer_name="Banco X",
        rate_pct=D(rate_pct),
        maturity_date=maturity,
        broker_id="banco-x",
        label="CDB Banco X",
    )


def flat_curve(start: date, end: date, rate: Decimal = CDI) -> CdiCurve:
    return CdiCurve(dict.fromkeys(b3_trading_days(start, end), rate))


def test_fator_diario_100_e_110_por_cento_do_cdi():
    assert daily_factor(CDI, D(100)) == D("1.00050788")
    assert daily_factor(CDI, D(110)) == D("1.000558668")


def test_tres_dias_de_cdi_a_100_por_cento_com_truncamento():
    curve = CdiCurve({date(2026, 3, 2): CDI, date(2026, 3, 3): CDI, date(2026, 3, 4): CDI})
    accrual = curve.accumulate(date(2026, 3, 2), date(2026, 3, 5))
    f = D("1.00050788")
    expected = trunc(trunc(f * f, 16) * f, 16)
    assert accrual.factor == expected
    assert accrual.last_rate_date == date(2026, 3, 4)
    assert trunc(D(10000) * accrual.factor, 2) == D("10015.24")


def test_no_dia_do_aporte_vale_o_principal_e_rende_a_partir_do_dia_seguinte():
    book = FixedIncomeBook(terms=terms(), curve=flat_curve(date(2026, 3, 2), date(2026, 3, 31)))
    book.apply(deposit(date(2026, 3, 2), "10000.00"))
    assert book.value_at(date(2026, 3, 2))[0] == D("10000.00")
    assert book.value_at(date(2026, 3, 3))[0] == D("10005.07")  # 10000 x 1,00050788 truncado


def test_fim_de_semana_nao_tem_taxa_e_nao_rende():
    book = FixedIncomeBook(terms=terms(), curve=flat_curve(date(2026, 3, 2), date(2026, 3, 31)))
    book.apply(deposit(date(2026, 3, 6), "10000.00"))  # sexta
    sabado = book.value_at(date(2026, 3, 7))[0]
    segunda = book.value_at(date(2026, 3, 9))[0]
    assert sabado == segunda == D("10005.07")


def test_110_por_cento_rende_mais_que_100_por_cento():
    curve = flat_curve(date(2026, 1, 2), date(2026, 12, 30))
    cem = FixedIncomeBook(terms=terms("100"), curve=curve)
    cento_e_dez = FixedIncomeBook(terms=terms("110"), curve=curve)
    for book in (cem, cento_e_dez):
        book.apply(deposit(date(2026, 1, 2), "10000.00"))
    v100 = cem.value_at(date(2026, 12, 30))[0]
    v110 = cento_e_dez.value_at(date(2026, 12, 30))[0]
    assert v110 > v100
    # Rendimento a 110% fica perto de 1,1 x o de 100% (um pouco acima, por juros compostos).
    assert Decimal("1.10") < (v110 - 10000) / (v100 - 10000) < Decimal("1.12")


def test_cdi_que_ainda_nao_saiu_nao_e_estimado():
    curve = CdiCurve(
        {date(2026, 3, 2): CDI, date(2026, 3, 3): CDI}
    )  # 04/03 em diante não publicado
    book = FixedIncomeBook(terms=terms(), curve=curve)
    book.apply(deposit(date(2026, 3, 2), "10000.00"))
    value, last = book.value_at(date(2026, 3, 6))
    assert last == date(2026, 3, 3)
    assert value == trunc(D(10000) * trunc(D("1.00050788") ** 2, 16), 2)


def test_rendimento_para_no_vencimento():
    curve = flat_curve(date(2026, 3, 2), date(2026, 6, 30))
    book = FixedIncomeBook(terms=terms(maturity=date(2026, 4, 1)), curve=curve)
    book.apply(deposit(date(2026, 3, 2), "10000.00"))
    assert book.value_at(date(2026, 4, 1)) == book.value_at(date(2026, 6, 30))


def test_resgate_parcial_consome_lotes_por_fifo():
    curve = flat_curve(date(2026, 3, 2), date(2026, 6, 30))
    book = FixedIncomeBook(terms=terms(), curve=curve)
    book.apply(deposit(date(2026, 3, 2), "1000.00"))
    book.apply(deposit(date(2026, 4, 1), "1000.00"))
    day = date(2026, 5, 4)
    v1 = book._lot_value(book.lots[0], day)[0]
    v2 = book._lot_value(book.lots[1], day)[0]
    book.apply(redeem(day, "1200.00"))
    assert len(book.lots) == 1
    assert book.lots[0].start == date(2026, 4, 1)  # o lote mais antigo saiu primeiro
    fraction = (D("1200.00") - v1) / v2
    assert book.lots[0].principal == D(1000) - D(1000) * fraction
    assert book.realized_pnl == (v1 - 1000) + ((D("1200.00") - v1) - D(1000) * fraction)


def test_resgate_maior_que_o_saldo_bruto_e_recusado():
    book = FixedIncomeBook(terms=terms(), curve=flat_curve(date(2026, 3, 2), date(2026, 3, 31)))
    book.apply(deposit(date(2026, 3, 2), "1000.00"))
    with pytest.raises(RedemptionExceedsBalanceError):
        book.apply(redeem(date(2026, 3, 10), "1100.00"))


def test_resgate_total_com_diferenca_de_centavos_fecha_a_posicao():
    book = FixedIncomeBook(terms=terms(), curve=flat_curve(date(2026, 3, 2), date(2026, 3, 31)))
    book.apply(deposit(date(2026, 3, 2), "1000.00"))
    balance = book.value_at(date(2026, 3, 10))[0]
    book.apply(redeem(date(2026, 3, 10), str(balance + D("0.03"))))
    assert book.lots == []
    assert book.cost_basis == 0


def test_resgate_no_mesmo_dia_de_outro_aporte_usa_valor_do_dia():
    curve = flat_curve(date(2026, 3, 2), date(2026, 3, 31))
    book = FixedIncomeBook(terms=terms(), curve=curve)
    book.apply(deposit(date(2026, 3, 2), "500.00"))
    day = date(2026, 3, 2) + timedelta(days=7)
    book.apply(deposit(day, "500.00"))
    book.apply(redeem(day, "100.00"))
    assert book.cost_basis < D(1000)
