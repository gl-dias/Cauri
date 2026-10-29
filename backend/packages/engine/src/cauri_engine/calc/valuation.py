"""Snapshots diários da carteira de um usuário a partir do ledger.

Para cada dia de pregão do intervalo: aplica as movimentações até aquele dia, avalia
cada posição (ativo x corretora) e atualiza as cotas da carteira inteira, de cada
classe e de cada corretora.

Preço de mercado nunca é estimado:
  * existe preço no dia esperado: ``ok``;
  * só existe preço mais antigo: usa o último válido, marcado ``stale`` com a data;
  * nunca houve preço: ``missing``, e a posição entra pelo custo (sinalizada).
O Tesouro tem um dia de defasagem esperada (o PU sai na manhã seguinte).
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from cauri_core import AssetClass, FixedIncomeTerms, Movement, MovementType, PriceStatus
from cauri_core.calendar import previous_trading_day
from cauri_core.money import ONE, ZERO, q2
from cauri_engine.calc.fixed_income import CdiCurve, FixedIncomeBook
from cauri_engine.calc.ordering import in_order
from cauri_engine.calc.performance import cdi_index, ipca_index, next_quota
from cauri_engine.calc.positions import AssetBook

# Defasagem esperada do preço, em pregões, por classe.
_EXPECTED_LAG: dict[AssetClass, int] = {
    AssetClass.ACAO: 0,
    AssetClass.FII: 0,
    AssetClass.CRIPTO: 0,
    AssetClass.TESOURO: 1,
}


@dataclass(frozen=True, slots=True)
class AssetInfo:
    id: UUID
    ticker: str
    asset_class: AssetClass


class PriceBook:
    """Fechamentos em BRL por ativo, com busca do último preço até uma data."""

    def __init__(self, closes: Mapping[UUID, Mapping[date, Decimal]]) -> None:
        self._dates: dict[UUID, list[date]] = {}
        self._values: dict[UUID, list[Decimal]] = {}
        for asset_id, series in closes.items():
            ordered = sorted(series)
            self._dates[asset_id] = ordered
            self._values[asset_id] = [series[d] for d in ordered]

    def last_on_or_before(self, asset_id: UUID, on: date) -> tuple[Decimal, date] | None:
        dates = self._dates.get(asset_id)
        if not dates:
            return None
        i = bisect_right(dates, on)
        if i == 0:
            return None
        return self._values[asset_id][i - 1], dates[i - 1]


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    snap_date: date
    asset_class: AssetClass
    broker_id: str
    asset_id: UUID | None
    instrument_id: UUID | None
    quantity: Decimal | None
    avg_cost: Decimal | None
    cost_basis: Decimal
    price: Decimal | None
    price_date: date | None
    price_status: PriceStatus
    market_value: Decimal
    realized_pnl: Decimal
    income_cum: Decimal


@dataclass(frozen=True, slots=True)
class BucketSnapshot:
    """Uma carteira, uma classe ou uma corretora num dia."""

    market_value: Decimal
    cost_basis: Decimal
    net_flows: Decimal
    income: Decimal
    quota_value: Decimal


@dataclass(frozen=True, slots=True)
class DaySnapshot:
    snap_date: date
    positions: tuple[PositionSnapshot, ...]
    total: BucketSnapshot
    by_class: Mapping[AssetClass, BucketSnapshot]
    by_broker: Mapping[str, BucketSnapshot]
    cdi_index: Decimal
    ipca_index: Decimal
    stale_count: int
    # Quanto valeria o mesmo dinheiro, com as mesmas entradas e saídas nas mesmas datas,
    # se tivesse rendido 100% do CDI. É a linha "CDI" do gráfico de evolução.
    cdi_equivalent: Decimal = ZERO


@dataclass(slots=True)
class _Flows:
    inflow: Decimal = ZERO
    outflow: Decimal = ZERO
    income: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return self.inflow - self.outflow


@dataclass(slots=True)
class _QuotaState:
    quota: Decimal = ONE
    prev_value: Decimal = ZERO


@dataclass(slots=True)
class _Accumulator:
    value: Decimal = ZERO
    cost: Decimal = ZERO


@dataclass
class PortfolioInputs:
    movements: Sequence[Movement]
    assets: Mapping[UUID, AssetInfo]
    instruments: Mapping[UUID, FixedIncomeTerms]
    prices: PriceBook
    cdi: CdiCurve
    ipca_monthly: Mapping[date, Decimal] = field(default_factory=dict)


def _flows_of(m: Movement, prices: PriceBook, day: date) -> _Flows:
    match m.type:
        case MovementType.COMPRA:
            assert m.quantity is not None
            assert m.unit_price is not None
            if m.opening_balance and m.asset_id is not None:
                # Saldo inicial entra pelo valor de mercado do dia: o custo informado vale
                # para o preço médio, mas a diferença para o mercado é anterior ao histórico
                # e não pode aparecer como rendimento no dia em que o saldo entra.
                found = prices.last_on_or_before(m.asset_id, day)
                if found is not None:
                    return _Flows(inflow=m.quantity * found[0])
            return _Flows(inflow=m.quantity * m.unit_price + m.fees)
        case MovementType.VENDA:
            assert m.quantity is not None
            assert m.unit_price is not None
            return _Flows(outflow=m.quantity * m.unit_price - m.fees)
        case MovementType.APORTE:
            assert m.amount is not None
            return _Flows(inflow=m.amount)
        case MovementType.RESGATE:
            assert m.amount is not None
            return _Flows(outflow=m.amount)
        case MovementType.PROVENTO:
            assert m.amount is not None
            return _Flows(outflow=m.amount, income=m.amount)
        case _:
            return _Flows()


def _expected_price_date(asset_class: AssetClass, on: date) -> date:
    lag = _EXPECTED_LAG.get(asset_class, 0)
    expected = on
    for _ in range(lag):
        expected = previous_trading_day(expected)
    return expected


def compute_snapshots(inputs: PortfolioInputs, days: Iterable[date]) -> list[DaySnapshot]:
    """Snapshots para cada dia de ``days`` (em ordem), desde a primeira movimentação.

    Movimentações em dias fora de ``days`` (cripto no fim de semana, por exemplo)
    entram no próximo dia da lista.
    """
    movements = in_order(inputs.movements)
    if not movements:
        return []
    inception = movements[0].trade_date
    day_list = [d for d in sorted(days) if d >= inception]

    asset_books: dict[UUID, AssetBook] = defaultdict(AssetBook)
    fi_books: dict[UUID, FixedIncomeBook] = {}
    quotas_total = _QuotaState()
    quotas_class: dict[AssetClass, _QuotaState] = defaultdict(_QuotaState)
    quotas_broker: dict[str, _QuotaState] = defaultdict(_QuotaState)

    snapshots: list[DaySnapshot] = []
    cursor = 0
    shadow = ZERO
    prev_cdi = ONE
    for day in day_list:
        flows_total = _Flows()
        flows_class: dict[AssetClass, _Flows] = defaultdict(_Flows)
        flows_broker: dict[str, _Flows] = defaultdict(_Flows)

        while cursor < len(movements) and movements[cursor].trade_date <= day:
            m = movements[cursor]
            cursor += 1
            asset_class = _class_of(m, inputs)
            if m.asset_id is not None:
                asset_books[m.asset_id].apply(m)
            else:
                assert m.instrument_id is not None
                book = fi_books.get(m.instrument_id)
                if book is None:
                    book = FixedIncomeBook(
                        terms=inputs.instruments[m.instrument_id], curve=inputs.cdi
                    )
                    fi_books[m.instrument_id] = book
                book.apply(m)
            f = _flows_of(m, inputs.prices, day)
            for target in (flows_total, flows_class[asset_class], flows_broker[m.broker_id]):
                target.inflow += f.inflow
                target.outflow += f.outflow
                target.income += f.income

        positions = _value_positions(day, inputs, asset_books, fi_books)

        acc_total = _Accumulator()
        acc_class: dict[AssetClass, _Accumulator] = defaultdict(_Accumulator)
        acc_broker: dict[str, _Accumulator] = defaultdict(_Accumulator)
        for p in positions:
            for acc in (acc_total, acc_class[p.asset_class], acc_broker[p.broker_id]):
                acc.value += p.market_value
                acc.cost += p.cost_basis

        total = _advance(quotas_total, acc_total, flows_total)
        class_keys = set(acc_class) | set(flows_class) | set(quotas_class)
        broker_keys = set(acc_broker) | set(flows_broker) | set(quotas_broker)
        by_class = {
            k: _advance(
                quotas_class[k], acc_class.get(k, _Accumulator()), flows_class.get(k, _Flows())
            )
            for k in sorted(class_keys)
        }
        by_broker = {
            k: _advance(
                quotas_broker[k], acc_broker.get(k, _Accumulator()), flows_broker.get(k, _Flows())
            )
            for k in sorted(broker_keys)
        }

        day_cdi = cdi_index(inputs.cdi, inception, day)
        # Entradas do dia começam a render a partir do dia (como um aporte em CDB), então o
        # fator do dia só vale para o que já estava aplicado.
        shadow = q2(shadow * day_cdi / prev_cdi + flows_total.inflow - flows_total.outflow)
        prev_cdi = day_cdi

        snapshots.append(
            DaySnapshot(
                snap_date=day,
                positions=tuple(positions),
                total=total,
                by_class=by_class,
                by_broker=by_broker,
                cdi_index=day_cdi,
                ipca_index=ipca_index(inputs.ipca_monthly, inception, day),
                stale_count=sum(1 for p in positions if p.price_status is not PriceStatus.OK),
                cdi_equivalent=shadow,
            )
        )
    return snapshots


def _class_of(m: Movement, inputs: PortfolioInputs) -> AssetClass:
    if m.instrument_id is not None:
        return AssetClass.RENDA_FIXA
    assert m.asset_id is not None
    return inputs.assets[m.asset_id].asset_class


def _advance(state: _QuotaState, acc: _Accumulator, flows: _Flows) -> BucketSnapshot:
    value = q2(acc.value)
    state.quota = next_quota(state.quota, state.prev_value, value, flows.inflow, flows.outflow)
    state.prev_value = value
    return BucketSnapshot(
        market_value=value,
        cost_basis=q2(acc.cost),
        net_flows=q2(flows.net),
        income=q2(flows.income),
        quota_value=state.quota,
    )


def _value_positions(
    day: date,
    inputs: PortfolioInputs,
    asset_books: Mapping[UUID, AssetBook],
    fi_books: Mapping[UUID, FixedIncomeBook],
) -> list[PositionSnapshot]:
    positions: list[PositionSnapshot] = []

    for asset_id, book in asset_books.items():
        if book.quantity <= 0:
            continue
        info = inputs.assets[asset_id]
        found = inputs.prices.last_on_or_before(asset_id, day)
        if found is None:
            price, price_date, status = None, None, PriceStatus.MISSING
        else:
            price, price_date = found
            fresh = price_date >= _expected_price_date(info.asset_class, day)
            status = PriceStatus.OK if fresh else PriceStatus.STALE
        avg_cost = book.avg_cost
        for broker_id, quantity in sorted(book.quantity_by_broker.items()):
            if quantity <= 0:
                continue
            cost = book.cost_basis * quantity / book.quantity
            value = q2(quantity * price) if price is not None else q2(cost)
            positions.append(
                PositionSnapshot(
                    snap_date=day,
                    asset_class=info.asset_class,
                    broker_id=broker_id,
                    asset_id=asset_id,
                    instrument_id=None,
                    quantity=quantity,
                    avg_cost=avg_cost,
                    cost_basis=q2(cost),
                    price=price,
                    price_date=price_date,
                    price_status=status,
                    market_value=value,
                    realized_pnl=q2(book.realized_by_broker.get(broker_id, ZERO)),
                    income_cum=q2(book.income_by_broker.get(broker_id, ZERO)),
                )
            )

    for instrument_id, fi in fi_books.items():
        if not fi.lots:
            continue
        value, last_rate = fi.value_at(day)
        accrual_target = min(day, fi.terms.maturity_date)
        expected = (
            previous_trading_day(accrual_target)
            if accrual_target > min(lot.start for lot in fi.lots)
            else None
        )
        fresh = expected is None or (last_rate is not None and last_rate >= expected)
        positions.append(
            PositionSnapshot(
                snap_date=day,
                asset_class=AssetClass.RENDA_FIXA,
                broker_id=fi.terms.broker_id,
                asset_id=None,
                instrument_id=instrument_id,
                quantity=None,
                avg_cost=None,
                cost_basis=q2(fi.cost_basis),
                price=None,
                price_date=last_rate,
                price_status=PriceStatus.OK if fresh else PriceStatus.STALE,
                market_value=value,
                realized_pnl=q2(fi.realized_pnl),
                income_cum=q2(fi.income),
            )
        )
    return positions
