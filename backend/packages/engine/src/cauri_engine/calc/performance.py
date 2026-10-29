"""Rentabilidade pelo método de cotas (TWR diário) e índices de referência.

A cota neutraliza aportes e resgates: o retorno do dia compara o valor de fechamento
com o valor de abertura mais o que entrou. Entradas (compras, aportes) contam como
se tivessem entrado no começo do dia, então o ganho do preço de compra até o
fechamento já aparece no dia. Saídas (vendas, resgates, proventos) contam como se
tivessem saído no fim do dia: o provento é retorno que sai da carteira em dinheiro.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from cauri_core.dates import add_months, days_in_month, month_start
from cauri_core.money import ONE, ZERO
from cauri_engine.calc.fixed_income import CdiCurve

HUNDRED = Decimal(100)


def daily_return(prev_value: Decimal, value: Decimal, inflow: Decimal, outflow: Decimal) -> Decimal:
    """Retorno do dia; zero quando não havia nada investido nem entrou nada."""
    base = prev_value + inflow
    if base <= 0:
        return ZERO
    return (value + outflow - prev_value - inflow) / base


def next_quota(
    prev_quota: Decimal, prev_value: Decimal, value: Decimal, inflow: Decimal, outflow: Decimal
) -> Decimal:
    return prev_quota * (ONE + daily_return(prev_value, value, inflow, outflow))


def period_return(quota_start: Decimal, quota_end: Decimal) -> Decimal:
    """Rentabilidade entre duas cotas (``quota_start`` é a do fechamento anterior ao período)."""
    return quota_end / quota_start - ONE


def cdi_index(curve: CdiCurve, inception: date, on: date) -> Decimal:
    """CDI acumulado (100%) desde ``inception`` até ``on``, mesma convenção da renda fixa."""
    return curve.accumulate(inception, on).factor


def ipca_index(monthly_pct: Mapping[date, Decimal], inception: date, on: date) -> Decimal:
    """IPCA acumulado de ``inception`` até ``on``, só com meses já publicados.

    A variação do mês m entra no primeiro dia do mês seguinte (quando o mês acabou).
    O mês de início entra proporcional aos dias corridos restantes, para um período
    que começa no meio do mês não ganhar o mês inteiro. Um mês sem publicação
    interrompe o acúmulo: nada de IPCA estimado.
    """
    index = ONE
    month = month_start(inception)
    while add_months(month, 1) <= on:
        pct = monthly_pct.get(month)
        if pct is None:
            break
        factor = ONE + pct / HUNDRED
        if month == month_start(inception) and inception.day > 1:
            total_days = days_in_month(month)
            remaining = Decimal(total_days - inception.day + 1) / Decimal(total_days)
            factor = factor**remaining
        index *= factor
        month = add_months(month, 1)
    return index
