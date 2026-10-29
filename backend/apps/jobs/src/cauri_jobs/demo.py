"""Carteira fictícia do /demo: 12 meses de movimentações coerentes com preços reais.

Os preços de compra e venda saem dos fechamentos reais de cada dia (com uma variação
pequena, como um preço intradiário); as quantidades, os aportes e os proventos são
inventados, com tamanho plausível. Nada aqui é a carteira de alguém.

A geração é determinística (semente fixa): os mesmos preços produzem o mesmo ledger.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal
from functools import partial

from cauri_core import AssetClass, FiKind, IncomeKind, MovementType, Origin
from cauri_core.calendar import b3_trading_days
from cauri_core.dates import add_months
from cauri_core.money import q2
from cauri_ledger import FixedIncomeDraft, MovementDraft

DEMO_EMAIL = "demo@cauri.invalid"
DEMO_NAME = "Investidor Demo"
SEED = 20261029

PriceLookup = Callable[[str, date], Decimal]


@dataclass(frozen=True, slots=True)
class DemoEntry:
    origin: Origin
    origin_label: str | None
    draft: MovementDraft


@dataclass(frozen=True, slots=True)
class _Position:
    ticker: str
    asset_class: AssetClass
    broker: str
    initial_value: int


def _plan(tesouro_selic: str, tesouro_ipca: str) -> list[_Position]:
    return [
        _Position("PETR4", AssetClass.ACAO, "xp", 6000),
        _Position("ITUB4", AssetClass.ACAO, "xp", 5000),
        _Position("TAEE11", AssetClass.ACAO, "xp", 3000),
        _Position("WEGE3", AssetClass.ACAO, "btg", 4000),
        _Position("VALE3", AssetClass.ACAO, "btg", 4500),
        _Position("BBAS3", AssetClass.ACAO, "btg", 3500),
        _Position("HGLG11", AssetClass.FII, "xp", 4500),
        _Position("MXRF11", AssetClass.FII, "xp", 3000),
        _Position("KNRI11", AssetClass.FII, "btg", 3500),
        _Position("XPML11", AssetClass.FII, "btg", 3000),
        _Position(tesouro_selic, AssetClass.TESOURO, "btg", 8000),
        _Position(tesouro_ipca, AssetClass.TESOURO, "btg", 6000),
        _Position("BTC", AssetClass.CRIPTO, "binance", 4000),
        _Position("ETH", AssetClass.CRIPTO, "binance", 2000),
        _Position("SOL", AssetClass.CRIPTO, "binance", 1000),
    ]


DEMO_B3_TICKERS = (
    "PETR4",
    "ITUB4",
    "TAEE11",
    "WEGE3",
    "VALE3",
    "BBAS3",
    "HGLG11",
    "MXRF11",
    "KNRI11",
    "XPML11",
)
DEMO_CRYPTO_TICKERS = ("BTC", "ETH", "SOL")
_ORIGIN_BY_BROKER: dict[str, tuple[Origin, str | None]] = {
    "xp": (Origin.IMPORT, "Planilha XP"),
    "btg": (Origin.IMPORT, "Planilha BTG"),
    "binance": (Origin.MANUAL, "Manual"),
    "nubank": (Origin.MANUAL, "Manual"),
    "inter": (Origin.MANUAL, "Manual"),
}
_QTY_PLACES = {AssetClass.ACAO: 0, AssetClass.FII: 0, AssetClass.TESOURO: 2, AssetClass.CRIPTO: 6}
_FEE_RATE = {
    AssetClass.ACAO: Decimal("0.0003"),
    AssetClass.FII: Decimal("0.0003"),
    AssetClass.TESOURO: Decimal(0),
    AssetClass.CRIPTO: Decimal("0.001"),
}
_ROTATION = ("ITUB4", "HGLG11", "WEGE3", "KNRI11", "TAEE11", "XPML11", "PETR4", "MXRF11", "BBAS3")
_STOCK_INCOME = {
    "PETR4": IncomeKind.DIVIDENDO,
    "ITUB4": IncomeKind.JCP,
    "BBAS3": IncomeKind.JCP,
    "TAEE11": IncomeKind.DIVIDENDO,
}


def _first_trading_day_from(day: date, until: date) -> date | None:
    return next(b3_trading_days(day, until), None)


def _floor(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


class _Builder:
    def __init__(
        self, price: PriceLookup, plan: list[_Position], today: date, generation: str
    ) -> None:
        self.price = price
        self.today = today
        self.generation = generation
        self.rng = random.Random(SEED)
        self.classes = {p.ticker: p.asset_class for p in plan}
        self.brokers = {p.ticker: p.broker for p in plan}
        self.holdings: dict[str, Decimal] = defaultdict(Decimal)
        self.entries: list[DemoEntry] = []
        self._n = 0

    def _key(self) -> str:
        self._n += 1
        return f"demo:{self.generation}:{self._n:04d}"

    def _trade_price(self, ticker: str, day: date) -> Decimal:
        close = self.price(ticker, day)
        if self.classes[ticker] is AssetClass.TESOURO:
            return q2(close)
        noise = Decimal(self.rng.randint(-40, 40)) / Decimal(10000)  # até 0,4% do fechamento
        return q2(close * (1 + noise))

    def _origin(self, ticker: str, via_chat: bool) -> tuple[Origin, str | None]:
        if via_chat:
            return Origin.CHAT, "Chat"
        return _ORIGIN_BY_BROKER[self.brokers[ticker]]

    def buy(self, ticker: str, day: date, value: Decimal, *, via_chat: bool = False) -> None:
        asset_class = self.classes[ticker]
        price = self._trade_price(ticker, day)
        quantity = _floor(value / price, _QTY_PLACES[asset_class])
        if quantity <= 0:
            quantity = Decimal(1).scaleb(-_QTY_PLACES[asset_class])
        fees = q2(quantity * price * _FEE_RATE[asset_class])
        origin, label = self._origin(ticker, via_chat)
        self.entries.append(
            DemoEntry(
                origin,
                label,
                MovementDraft(
                    idempotency_key=self._key(),
                    trade_date=day,
                    type=MovementType.COMPRA,
                    broker_id=self.brokers[ticker],
                    ticker=ticker,
                    quantity=quantity,
                    unit_price=price,
                    fees=fees,
                ),
            )
        )
        self.holdings[ticker] += quantity

    def sell_fraction(self, ticker: str, day: date, fraction: Decimal) -> None:
        asset_class = self.classes[ticker]
        quantity = _floor(self.holdings[ticker] * fraction, _QTY_PLACES[asset_class])
        if quantity <= 0:
            return
        price = self._trade_price(ticker, day)
        fees = q2(quantity * price * _FEE_RATE[asset_class])
        origin, label = self._origin(ticker, via_chat=False)
        self.entries.append(
            DemoEntry(
                origin,
                label,
                MovementDraft(
                    idempotency_key=self._key(),
                    trade_date=day,
                    type=MovementType.VENDA,
                    broker_id=self.brokers[ticker],
                    ticker=ticker,
                    quantity=quantity,
                    unit_price=price,
                    fees=fees,
                ),
            )
        )
        self.holdings[ticker] -= quantity

    def income(
        self,
        ticker: str,
        day: date,
        yield_pct: Decimal,
        kind: IncomeKind,
        *,
        price_day: date | None = None,
    ) -> None:
        held = self.holdings[ticker]
        if held <= 0:
            return
        per_unit = q2(self.price(ticker, price_day or day) * yield_pct)
        amount = q2(held * per_unit)
        if amount <= 0:
            return
        origin, label = self._origin(ticker, via_chat=False)
        self.entries.append(
            DemoEntry(
                origin,
                label,
                MovementDraft(
                    idempotency_key=self._key(),
                    trade_date=day,
                    type=MovementType.PROVENTO,
                    broker_id=self.brokers[ticker],
                    ticker=ticker,
                    amount=amount,
                    income_kind=kind,
                ),
            )
        )

    def fixed_income(
        self, kind: MovementType, terms: FixedIncomeDraft, broker: str, day: date, amount: Decimal
    ) -> None:
        self.entries.append(
            DemoEntry(
                Origin.MANUAL,
                "Manual",
                MovementDraft(
                    idempotency_key=self._key(),
                    trade_date=day,
                    type=kind,
                    broker_id=broker,
                    fixed_income=terms,
                    amount=q2(amount),
                ),
            )
        )


def generate(
    price: PriceLookup,
    *,
    today: date,
    tesouro_selic: str,
    tesouro_ipca: str,
    generation: str,
    months: int = 12,
) -> list[DemoEntry]:
    """Movimentações do demo, em ordem cronológica, de ``months`` meses atrás até hoje.

    ``generation`` entra na chave de idempotência: depois de um reset, as chaves das
    movimentações anuladas continuam ocupadas (o ledger nunca apaga), então cada geração
    precisa das suas.
    """
    plan = _plan(tesouro_selic, tesouro_ipca)
    b = _Builder(price, plan, today, generation)
    start = _first_trading_day_from(add_months(today, -months), today)
    if start is None:  # pragma: no cover - sempre há pregão em 12 meses
        raise ValueError("sem pregão no período do demo")
    last_trade_day = today - timedelta(days=1)

    cdb = FixedIncomeDraft(FiKind.CDB, "Banco Demo", Decimal(110), add_months(start, 24))
    lci = FixedIncomeDraft(FiKind.LCI, "Banco Exemplo", Decimal(95), add_months(start, 18))

    # Carteira inicial.
    for position in plan:
        b.buy(position.ticker, start, Decimal(position.initial_value))
    b.fixed_income(MovementType.APORTE, cdb, "nubank", start, Decimal(15000))
    b.fixed_income(MovementType.APORTE, lci, "inter", start, Decimal(10000))

    for month in range(1, months + 1):
        anchor = add_months(start, month).replace(day=1)
        if anchor > last_trade_day:
            break
        # (dia do mês, ordem dentro do dia, ação que recebe a data do pregão)
        schedule: list[tuple[int, int, Callable[[date], None]]] = []

        # Aporte mensal em 2 ativos da rotação; de três em três meses, pelo chat.
        total = Decimal(round(4000 * b.rng.uniform(0.8, 1.2) / 100) * 100)
        via_chat = month % 3 == 0
        for offset in (0, 1):
            ticker = _ROTATION[(2 * month + offset) % len(_ROTATION)]
            schedule.append((10, 1, partial(b.buy, ticker, value=total / 2, via_chat=via_chat)))
        schedule.append((20, 1, partial(b.buy, "BTC", value=Decimal(300))))

        # Rendimentos mensais dos FIIs (0,75% a 0,95% do preço por cota).
        for fii in ("HGLG11", "MXRF11", "KNRI11", "XPML11"):
            yield_pct = Decimal(str(round(b.rng.uniform(0.0075, 0.0095), 4)))
            schedule.append(
                (15, 3, partial(b.income, fii, yield_pct=yield_pct, kind=IncomeKind.RENDIMENTO))
            )

        # Proventos trimestrais das ações.
        if month % 3 == 2:
            for stock, kind in _STOCK_INCOME.items():
                yield_pct = Decimal(str(round(b.rng.uniform(0.012, 0.025), 4)))
                schedule.append((22, 3, partial(b.income, stock, yield_pct=yield_pct, kind=kind)))

        # Vendas parciais e movimentos de renda fixa em meses específicos.
        if month == 5:
            schedule.append((12, 2, partial(b.sell_fraction, "VALE3", fraction=Decimal("0.5"))))
        if month == 6:
            aporte = partial(
                b.fixed_income, MovementType.APORTE, cdb, "nubank", amount=Decimal(5000)
            )
            schedule.append((5, 1, aporte))
        if month == 8:
            schedule.append((18, 2, partial(b.sell_fraction, "MXRF11", fraction=Decimal("0.3"))))
        if month == 9:
            schedule.append((8, 2, partial(b.sell_fraction, "SOL", fraction=Decimal("0.4"))))
        if month == 10:
            resgate = partial(
                b.fixed_income, MovementType.RESGATE, lci, "inter", amount=Decimal(3000)
            )
            schedule.append((25, 2, resgate))

        events: list[tuple[date, int, Callable[[date], None]]] = []
        for day_of_month, order, action in schedule:
            target = anchor.replace(day=min(day_of_month, 28))
            day = _first_trading_day_from(target, today) if target <= last_trade_day else None
            if day is not None and day <= last_trade_day:
                events.append((day, order, action))
        for day, _, action in sorted(events, key=lambda e: (e[0], e[1])):
            action(day)

    # Um rendimento já anunciado, com pagamento daqui a alguns dias (aparece na Agenda).
    payment = _first_trading_day_from(today + timedelta(days=7), today + timedelta(days=30))
    assert payment is not None
    b.income("HGLG11", payment, Decimal("0.0085"), IncomeKind.RENDIMENTO, price_day=last_trade_day)
    return b.entries


def price_lookup(
    closes: Mapping[str, Mapping[date, Decimal]], max_lag_days: int = 10
) -> PriceLookup:
    """Fechamento do dia ou o mais recente antes dele (no máximo ``max_lag_days`` antes)."""

    def lookup(ticker: str, day: date) -> Decimal:
        series = closes.get(ticker, {})
        for lag in range(max_lag_days + 1):
            value = series.get(day - timedelta(days=lag))
            if value is not None:
                return value
        raise LookupError(f"sem preço de {ticker} perto de {day:%d/%m/%Y}: rode o backfill antes")

    return lookup
