"""Gravação dos snapshots a partir do ledger, contra o banco local."""

from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

import pytest

from cauri_core import MovementType, Origin
from cauri_core.dates import SAO_PAULO
from cauri_engine.persist import last_closed_day, recalc_dirty, recalc_user
from cauri_ledger import Ledger, MovementDraft
from cauri_storage import admin_connection

pytestmark = pytest.mark.db

# Semana passada fixa (o banco recusa compra com data no futuro); seg a sex.
DAYS = [date(2025, 3, d) for d in (10, 11, 12, 13, 14)]


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=SAO_PAULO)


def test_ultimo_pregao_com_fechamento_disponivel():
    assert last_closed_day(at(date(2026, 10, 30), 17, 40)) == date(2026, 10, 30)  # fecha 17h
    assert last_closed_day(at(date(2026, 10, 30), 16, 0)) == date(2026, 10, 29)
    assert last_closed_day(at(date(2026, 11, 3), 18, 20)) == date(
        2026, 10, 30
    )  # fecha 18h; 02/11 é feriado
    assert last_closed_day(at(date(2026, 11, 3), 18, 31)) == date(2026, 11, 3)
    assert last_closed_day(at(date(2026, 11, 7), 12, 0)) == date(2026, 11, 6)  # sábado


@pytest.fixture
def priced_asset(admin_url, reference_data):
    """TSTB4 com fechamentos conhecidos na semana de teste."""
    asset_id = reference_data["TSTB4"]
    with admin_connection(admin_url) as conn:
        conn.execute(
            "delete from market.prices_daily where asset_id = %s and price_date between %s and %s",
            [asset_id, DAYS[0], DAYS[-1]],
        )
        for day, close in zip(DAYS, ("10.00", "11.00", "11.00", "9.90", "10.50"), strict=True):
            conn.execute(
                "insert into market.prices_daily (asset_id, price_date, currency, close, source)"
                " values (%s, %s, 'BRL', %s, 'teste')",
                [asset_id, day, Decimal(close)],
            )
    return asset_id


def buy(day: date, qty: str, price: str) -> MovementDraft:
    return MovementDraft(
        idempotency_key=f"teste-{uuid4()}",
        trade_date=day,
        type=MovementType.COMPRA,
        broker_id="corretora-teste-a",
        ticker="TSTB4",
        quantity=Decimal(qty),
        unit_price=Decimal(price),
    )


def snapshots(conn, user_id):
    return conn.execute(
        "select snap_date, market_value, quota_value, stale_count from engine.portfolio_snapshots"
        " where user_id = %s order by snap_date",
        [user_id],
    ).fetchall()


def test_recalculo_grava_dia_a_dia_e_e_idempotente(make_user, as_user, priced_asset):
    user = make_user()
    with as_user(user) as conn:
        Ledger(conn, today=DAYS[-1]).post(
            user.id, [buy(DAYS[0], "100", "10")], origin=Origin.MANUAL
        )
    with as_user(user) as conn:
        first = recalc_user(conn, user.id, from_date=DAYS[0], until=DAYS[-1])
        rows = snapshots(conn, user.id)
    assert first.days_written == 5
    assert [r["market_value"] for r in rows] == [
        Decimal(v) for v in ("1000.00", "1100.00", "1100.00", "990.00", "1050.00")
    ]
    assert rows[1]["quota_value"] == Decimal("1.1")
    with as_user(user) as conn:
        recalc_user(conn, user.id, from_date=DAYS[2], until=DAYS[-1])
        again = snapshots(conn, user.id)
        buckets = conn.execute(
            "select bucket_kind, bucket_key from engine.bucket_snapshots"
            " where user_id = %s and snap_date = %s",
            [user.id, DAYS[-1]],
        ).fetchall()
    assert again == rows
    assert {(b["bucket_kind"], b["bucket_key"]) for b in buckets} == {
        ("class", "acao"),
        ("broker", "corretora-teste-a"),
    }


def test_edicao_retroativa_marca_e_recalcula_a_partir_da_data(make_user, as_user, priced_asset):
    user = make_user()
    with as_user(user) as conn:
        Ledger(conn, today=DAYS[-1]).post(
            user.id, [buy(DAYS[0], "100", "10")], origin=Origin.MANUAL
        )
        recalc_dirty(conn, user.id, until=DAYS[-1])
    with as_user(user) as conn:
        Ledger(conn, today=DAYS[-1]).post(user.id, [buy(DAYS[2], "50", "11")], origin=Origin.MANUAL)
        dirty = conn.execute(
            "select from_date from engine.dirty_ranges where user_id = %s", [user.id]
        ).fetchone()
        result = recalc_dirty(conn, user.id, until=DAYS[-1])
        rows = snapshots(conn, user.id)
        left = conn.execute(
            "select count(*) as n from engine.dirty_ranges where user_id = %s", [user.id]
        ).fetchone()
    assert dirty == {"from_date": DAYS[2]}
    assert result is not None
    assert result.days_written == 3  # só de 12/03 em diante
    assert rows[2]["market_value"] == Decimal("1650.00")
    assert left == {"n": 0}


def test_movimentacao_removida_some_dos_snapshots(make_user, as_user, priced_asset):
    user = make_user()
    with as_user(user) as conn:
        created = Ledger(conn, today=DAYS[-1]).post(
            user.id, [buy(DAYS[0], "10", "10")], origin=Origin.MANUAL
        )
        recalc_dirty(conn, user.id, until=DAYS[-1])
    with as_user(user) as conn:
        Ledger(conn, today=DAYS[-1]).void(user.id, created.created[0], reason="lançada errado")
        recalc_dirty(conn, user.id, until=DAYS[-1])
        assert snapshots(conn, user.id) == []


def test_usuario_nao_grava_snapshot_de_outro(make_user, as_user, priced_asset):
    ana, bruno = make_user(), make_user()
    with as_user(ana) as conn:
        Ledger(conn, today=DAYS[-1]).post(ana.id, [buy(DAYS[0], "10", "10")], origin=Origin.MANUAL)
    with as_user(bruno) as conn, pytest.raises(Exception, match="row-level security"):
        # A carteira da ana nem aparece para o bruno; forçar a escrita esbarra no RLS.
        conn.execute(
            "insert into engine.portfolio_snapshots (user_id, snap_date, market_value, cost_basis,"
            " net_flows, quota_value, cdi_index, ipca_index) values (%s, %s, 1, 1, 0, 1, 1, 1)",
            [ana.id, DAYS[0]],
        )
