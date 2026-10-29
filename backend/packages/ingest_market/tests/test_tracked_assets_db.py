"""A lista de ativos do job é a UNIÃO das carteiras, sem repetir, lida pelo role do job."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from cauri_core import MovementType, Origin
from cauri_ingest_market import tracked_assets
from cauri_ledger import Ledger, MovementDraft
from cauri_storage import service_transaction

pytestmark = pytest.mark.db


def buy(ticker: str) -> MovementDraft:
    return MovementDraft(
        idempotency_key=f"teste-{uuid4()}",
        trade_date=date(2026, 1, 5),
        type=MovementType.COMPRA,
        broker_id="corretora-teste-a",
        ticker=ticker,
        quantity=Decimal(1),
        unit_price=Decimal(10),
    )


def test_uniao_das_carteiras_sem_repetir(make_user, reference_data, as_user, ingest_pool):
    ana, bruno = make_user(), make_user()
    with as_user(ana) as conn:
        Ledger(conn).post(ana.id, [buy("TSTA3"), buy("TSTF11")], origin=Origin.MANUAL)
    with as_user(bruno) as conn:
        Ledger(conn).post(bruno.id, [buy("TSTA3")], origin=Origin.MANUAL)
    with service_transaction(ingest_pool) as conn:
        tickers = [a.ticker for a in tracked_assets(conn, None)]
    assert tickers.count("TSTA3") == 1
    assert "TSTF11" in tickers


def test_lista_explicita_recusa_ativo_desconhecido(reference_data, ingest_pool):
    with service_transaction(ingest_pool) as conn, pytest.raises(ValueError, match="XXXX9"):
        tracked_assets(conn, ["TSTA3", "XXXX9"])
