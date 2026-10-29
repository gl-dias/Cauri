from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID

from cauri_core import AssetClass, FiKind, FixedIncomeTerms, PriceStatus
from cauri_core.calendar import b3_trading_days
from cauri_engine.calc import AssetInfo, CdiCurve, PortfolioInputs, PriceBook, compute_snapshots
from engine_factories import ASSET_A, ASSET_B, INSTRUMENT, D, buy, deposit, income, sell

TESOURO = UUID("10000000-0000-4000-8000-0000000000aa")
SEM_COTACAO = UUID("10000000-0000-4000-8000-0000000000bb")

MON, TUE, WED, THU, FRI = (date(2026, 3, d) for d in (2, 3, 4, 5, 6))
SAT = date(2026, 3, 7)
NEXT_MON = date(2026, 3, 9)
WEEK = list(b3_trading_days(MON, NEXT_MON))

ASSETS = {
    ASSET_A: AssetInfo(ASSET_A, "AAAA3", AssetClass.ACAO),
    ASSET_B: AssetInfo(ASSET_B, "CRIP", AssetClass.CRIPTO),
    TESOURO: AssetInfo(TESOURO, "TESOURO-SELIC-2031", AssetClass.TESOURO),
    SEM_COTACAO: AssetInfo(SEM_COTACAO, "NOVA3", AssetClass.ACAO),
}
CDB = FixedIncomeTerms(
    id=INSTRUMENT,
    kind=FiKind.CDB,
    issuer_name="Banco X",
    rate_pct=D(100),
    maturity_date=date(2028, 1, 3),
    broker_id="banco-x",
    label="CDB Banco X 100% CDI",
)


def inputs(movements, prices, cdi=None):
    return PortfolioInputs(
        movements=movements,
        assets=ASSETS,
        instruments={INSTRUMENT: CDB},
        prices=PriceBook(prices),
        cdi=CdiCurve(cdi or {}),
    )


def by_day(snapshots):
    return {s.snap_date: s for s in snapshots}


def test_carteira_simples_valor_e_cota_dia_a_dia():
    prices = {ASSET_A: {MON: D(10), TUE: D(11), WED: D(11), THU: D("9.90"), FRI: D(11)}}
    snaps = by_day(compute_snapshots(inputs([buy(MON, 100, 10)], prices), WEEK))
    assert snaps[MON].total.market_value == D("1000.00")
    assert snaps[MON].total.net_flows == D("1000.00")
    assert snaps[MON].total.quota_value == 1
    assert snaps[TUE].total.quota_value == D("1.1")
    assert snaps[THU].total.quota_value == D("0.99")
    assert snaps[FRI].positions[0].avg_cost == 10


def test_preco_que_falhou_usa_o_ultimo_valido_marcado_como_desatualizado():
    prices = {ASSET_A: {MON: D(10), TUE: D(11)}}  # quarta em diante a fonte falhou
    snaps = by_day(compute_snapshots(inputs([buy(MON, 10, 10)], prices), WEEK))
    wed = snaps[WED].positions[0]
    assert wed.price == D(11)
    assert wed.price_date == TUE
    assert wed.price_status is PriceStatus.STALE
    assert snaps[WED].stale_count == 1
    assert snaps[TUE].positions[0].price_status is PriceStatus.OK


def test_ativo_nunca_cotado_entra_pelo_custo_sinalizado():
    snaps = compute_snapshots(inputs([buy(MON, 10, 7, fees=1, asset=SEM_COTACAO)], {}), [MON])
    position = snaps[0].positions[0]
    assert position.price is None
    assert position.price_status is PriceStatus.MISSING
    assert position.market_value == D("71.00")


def test_tesouro_com_pu_do_dia_anterior_esta_em_dia():
    prices = {TESOURO: {MON: D("15000"), TUE: D("15010")}}
    snaps = by_day(
        compute_snapshots(inputs([buy(MON, "0.5", "15000", asset=TESOURO)], prices), [TUE, WED])
    )
    assert snaps[WED].positions[0].price_date == TUE
    assert snaps[WED].positions[0].price_status is PriceStatus.OK


def test_movimentacao_no_fim_de_semana_entra_no_proximo_pregao():
    prices = {ASSET_B: {FRI: D(100), SAT: D(110), NEXT_MON: D(120)}}
    snaps = by_day(compute_snapshots(inputs([buy(SAT, 1, 110, asset=ASSET_B)], prices), WEEK))
    assert FRI not in snaps
    assert snaps[NEXT_MON].total.net_flows == D("110.00")
    assert snaps[NEXT_MON].total.market_value == D("120.00")


def test_renda_fixa_entra_com_valor_bruto_e_cota_acompanha_o_cdi():
    cdi = dict.fromkeys(WEEK, D("0.05"))
    snaps = by_day(compute_snapshots(inputs([deposit(MON, "10000.00")], {}, cdi), WEEK))
    position = snaps[WED].positions[0]
    assert position.asset_class is AssetClass.RENDA_FIXA
    assert position.market_value == D("10010.00")  # 10000 x 1,0005^2 truncado
    assert position.price_date == TUE
    assert position.price_status is PriceStatus.OK
    # Carteira só com CDB a 100% do CDI: a cota é o próprio CDI acumulado.
    assert snaps[WED].total.quota_value == D("1.001")
    assert snaps[WED].cdi_index == D("1.0005") ** 2


def test_buckets_por_classe_e_por_corretora():
    prices = {ASSET_A: dict.fromkeys(WEEK, D(10)), ASSET_B: dict.fromkeys(WEEK, D(50))}
    movements = [
        buy(MON, 10, 10, broker="corretora-a"),
        buy(MON, 2, 50, asset=ASSET_B, broker="exchange-b"),
        sell(WED, 4, 12, broker="corretora-a"),
        income(THU, "5.00", broker="corretora-a"),
    ]
    snaps = by_day(compute_snapshots(inputs(movements, prices), WEEK))
    thu = snaps[THU]
    assert set(thu.by_class) == {AssetClass.ACAO, AssetClass.CRIPTO}
    assert set(thu.by_broker) == {"corretora-a", "exchange-b"}
    assert thu.by_class[AssetClass.ACAO].market_value == D("60.00")
    assert thu.by_class[AssetClass.CRIPTO].quota_value == 1
    assert thu.total.income == D("5.00")
    assert thu.by_broker["corretora-a"].net_flows == D("-5.00")
    position = next(p for p in thu.positions if p.asset_id == ASSET_A)
    assert position.realized_pnl == D("8.00")  # 4 x (12 - 10)
    assert position.income_cum == D("5.00")


def test_sem_movimentacoes_nao_gera_snapshot():
    assert compute_snapshots(inputs([], {}), WEEK) == []


def test_dias_antes_da_primeira_movimentacao_sao_ignorados():
    prices = {ASSET_A: dict.fromkeys(WEEK, D(10))}
    snaps = compute_snapshots(inputs([buy(WED, 1, 10)], prices), WEEK)
    assert next(s.snap_date for s in snaps) == WED
    assert all(isinstance(s.total.quota_value, Decimal) for s in snaps)


def test_linha_do_cdi_com_os_mesmos_fluxos():
    # Carteira só com CDB a 100% do CDI: a linha do CDI é o próprio patrimônio.
    cdi = dict.fromkeys(WEEK, D("0.05"))
    snaps = by_day(compute_snapshots(inputs([deposit(MON, "10000.00")], {}, cdi), WEEK))
    for day in (MON, WED, FRI):
        assert abs(snaps[day].cdi_equivalent - snaps[day].total.market_value) <= D("0.01")


def test_linha_do_cdi_desconta_as_mesmas_saidas():
    prices = {ASSET_A: dict.fromkeys(WEEK, D(10))}
    cdi = dict.fromkeys(WEEK, D("0.05"))
    movements = [buy(MON, 100, 10), sell(WED, 50, 10)]
    snaps = by_day(compute_snapshots(inputs(movements, prices, cdi), WEEK))
    assert snaps[MON].cdi_equivalent == D("1000.00")
    # 1000 rende 2 dias de CDI (seg->ter, ter->qua) e saem 500 na quarta.
    assert snaps[WED].cdi_equivalent == (D("1000.00") * D("1.0005") ** 2 - 500).quantize(D("0.01"))


def test_saldo_inicial_entra_pelo_mercado_e_nao_vira_rendimento_no_dia():
    """Saldo inicial com custo antigo (R$ 6) num dia em que o ativo vale R$ 10: o preço médio
    é o custo informado, mas a cota não sobe 66% no dia em que o saldo entra."""
    prices = {ASSET_A: {MON: D(10), TUE: D(11)}}
    opening = replace(buy(MON, 100, 6), opening_balance=True)
    snaps = by_day(compute_snapshots(inputs([opening], prices), [MON, TUE]))
    assert snaps[MON].total.net_flows == D("1000.00")  # entrada a mercado, não a custo
    assert snaps[MON].total.quota_value == 1
    assert snaps[TUE].total.quota_value == D("1.1")
    assert snaps[TUE].positions[0].avg_cost == 6
    assert snaps[TUE].total.cost_basis == D("600.00")
