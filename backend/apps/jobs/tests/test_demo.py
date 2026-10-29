"""Gerador da carteira demo com preços sintéticos (o seed real usa preços do banco)."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import NAMESPACE_DNS, uuid5

from cauri_core import Movement, MovementType, Origin
from cauri_engine.calc import find_oversell
from cauri_jobs.demo import DEMO_B3_TICKERS, DEMO_CRYPTO_TICKERS, generate, price_lookup
from cauri_ledger.validation import check_shape

TODAY = date(2026, 10, 29)
SELIC, IPCA = "TD-SELIC-01032028", "TD-IPCA-15052035"
TICKERS = [*DEMO_B3_TICKERS, *DEMO_CRYPTO_TICKERS, SELIC, IPCA]


def flat_prices():
    days = [TODAY - timedelta(days=i) for i in range(400)]
    return {t: {d: Decimal(100 + i) for d in days} for i, t in enumerate(TICKERS)}


def entries(generation="teste"):
    return generate(
        price_lookup(flat_prices()),
        today=TODAY,
        tesouro_selic=SELIC,
        tesouro_ipca=IPCA,
        generation=generation,
    )


def as_movements(items):
    movements = []
    for seq, e in enumerate(items):
        d = e.draft
        key = d.ticker or (d.fixed_income.display_label() if d.fixed_income else "")
        asset = uuid5(NAMESPACE_DNS, key)
        movements.append(
            Movement(
                id=uuid5(NAMESPACE_DNS, d.idempotency_key),
                trade_date=d.trade_date,
                type=d.type,
                broker_id=d.broker_id,
                asset_id=asset if d.ticker else None,
                instrument_id=None if d.ticker else asset,
                quantity=d.quantity,
                unit_price=d.unit_price,
                fees=d.fees,
                amount=d.amount,
                factor=d.factor,
                income_kind=d.income_kind,
                seq=seq,
            )
        )
    return movements


def test_doze_meses_em_ordem_cronologica_ate_hoje():
    items = entries()
    dates = [e.draft.trade_date for e in items]
    past = [d for d in dates if d <= TODAY]
    assert past == sorted(past)
    assert min(dates) >= date(2025, 10, 29)
    assert max(past) < TODAY
    assert any(d.month == 10 and d.year == 2026 for d in past), (
        "o mês corrente também tem atividade"
    )


def test_todas_as_movimentacoes_passam_nas_regras_do_ledger():
    for e in entries():
        assert check_shape(e.draft, TODAY) == [], e.draft


def test_nenhuma_venda_descoberta():
    movements = [m for m in as_movements(entries()) if m.asset_id is not None]
    assert find_oversell(movements) is None


def test_tem_as_cinco_classes_varias_corretoras_e_as_tres_origens():
    items = entries()
    assert {e.origin for e in items} == {Origin.IMPORT, Origin.MANUAL, Origin.CHAT}
    assert {e.draft.broker_id for e in items} >= {"xp", "btg", "nubank", "inter", "binance"}
    tickers = {e.draft.ticker for e in items if e.draft.ticker}
    assert {"PETR4", "HGLG11", SELIC, "BTC"} <= tickers
    assert any(e.draft.fixed_income for e in items)
    types = {e.draft.type for e in items}
    assert {
        MovementType.COMPRA,
        MovementType.VENDA,
        MovementType.APORTE,
        MovementType.RESGATE,
        MovementType.PROVENTO,
    } <= types


def test_um_provento_anunciado_para_os_proximos_dias():
    futuros = [e for e in entries() if e.draft.trade_date > TODAY]
    assert len(futuros) == 1
    assert futuros[0].draft.type is MovementType.PROVENTO


def test_chaves_unicas_e_com_a_geracao():
    a, b = entries("aaaa"), entries("bbbb")
    keys_a = [e.draft.idempotency_key for e in a]
    assert len(set(keys_a)) == len(keys_a)
    assert all(k.startswith("demo:aaaa:") for k in keys_a)
    assert not set(keys_a) & {e.draft.idempotency_key for e in b}


def test_deterministico_para_os_mesmos_precos():
    assert [e.draft for e in entries()] == [e.draft for e in entries()]
