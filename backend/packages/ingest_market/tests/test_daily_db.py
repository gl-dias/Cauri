"""Job diário contra o banco local, com as fontes simuladas (nenhuma chamada de rede).

Usa só ativos de teste, para nunca gravar preço falso de ativo real no banco local.
"""

import json
from datetime import date
from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from cauri_ingest_market import run_daily
from cauri_storage import admin_connection, service_transaction

pytestmark = pytest.mark.db

DAY = date(2030, 10, 31)  # quinta, com horário de verão americano: fecha às 17h (data longe
# do presente para não esbarrar em preços nem na cota do mês corrente no banco local)
TICKERS = ["TSTA3", "TSTF11", "TSTCOIN", "TD-PRE-01012099"]


@pytest.fixture
def test_assets(admin_url, reference_data):
    """Ativos de teste com id de cripto e um título do Tesouro fictício; zera os preços do dia."""
    with admin_connection(admin_url) as conn:
        conn.execute(
            "update market.assets set provider_ids = provider_ids || %s::jsonb"
            " where ticker = 'TSTCOIN'",
            ['{"coingecko": "cauri-test-coin"}'],
        )
        conn.execute(
            "insert into market.issuers (code, name) values ('TESOURO', 'Tesouro Nacional')"
            " on conflict (code) do nothing"
        )
        conn.execute(
            "insert into market.assets (ticker, class, issuer_code, name, maturity_date)"
            " values ('TD-PRE-01012099', 'tesouro', 'TESOURO', 'Tesouro de teste', '2099-01-01')"
            " on conflict (ticker) do nothing"
        )
        ids = {
            r["ticker"]: r["id"]
            for r in conn.execute(
                "select ticker, id from market.assets where ticker = any(%s)", [TICKERS]
            )
        }
        conn.execute(
            "delete from market.prices_daily where asset_id = any(%s)", [list(ids.values())]
        )
        conn.execute("delete from ops.quota_usage where source = 'brapi' and month = '2030-10-01'")
    return ids


def mock_client(calls: list[str], *, brapi_status: int = 200, before_close: set[str] = frozenset()):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if "brapi.dev" in url:
            ticker = url.rsplit("/", 1)[-1]
            if brapi_status != 200:
                return httpx.Response(brapi_status, json={"message": "limite"})
            when = (
                "2030-10-31T19:30:00.000Z" if ticker in before_close else "2030-10-31T20:03:00.000Z"
            )
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"symbol": ticker, "regularMarketPrice": 12.34, "regularMarketTime": when}
                    ]
                },
            )
        if "coingecko" in url:
            return httpx.Response(200, json={"cauri-test-coin": {"brl": 501.5, "usd": 92.1}})
        if "tesourotransparente" in url:
            csv = (
                "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
                "PU Compra Manha;PU Venda Manha;PU Base Manha\n"
                "Tesouro Prefixado;01/01/2099;30/10/2030;12,00;12,10;10,10;10,00;10,00\n"
            )
            return httpx.Response(200, content=csv.encode())
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def prices(admin_url: str, ids: dict[str, UUID]) -> dict[tuple[str, str], Decimal]:
    names = {v: k for k, v in ids.items()}
    with admin_connection(admin_url) as conn:
        rows = conn.execute(
            "select asset_id, price_date, currency, close, source from market.prices_daily"
            " where asset_id = any(%s)",
            [list(ids.values())],
        ).fetchall()
    return {
        (names[r["asset_id"]], f"{r['price_date']}:{r['currency']}:{r['source']}"): r["close"]
        for r in rows
    }


def run(ingest_pool, client, *, second=False, quota=15_000):
    return run_daily(
        ingest_pool,
        day=DAY,
        second_pass=second,
        client=client,
        brapi_token="token-de-teste",
        coingecko_key=None,
        tickers=TICKERS,
        sources={"brapi", "coingecko", "tesouro"},
        brapi_monthly_quota=quota,
        brapi_pause_s=0,
    )


def test_primeira_passada_grava_fechamentos_e_log_por_fonte(ingest_pool, admin_url, test_assets):
    calls: list[str] = []
    with mock_client(calls) as client:
        report = run(ingest_pool, client)
    got = prices(admin_url, test_assets)
    assert got[("TSTA3", "2030-10-31:BRL:brapi")] == Decimal("12.34")
    assert got[("TSTF11", "2030-10-31:BRL:brapi")] == Decimal("12.34")
    assert got[("TSTCOIN", "2030-10-31:USD:coingecko")] == Decimal("92.1")
    assert got[("TD-PRE-01012099", "2030-10-30:BRL:tesouro")] == Decimal("10.00")  # PU de D-1
    assert report.status == "ok"
    with service_transaction(ingest_pool) as conn:
        statuses = {
            r["source"]: r["status"]
            for r in conn.execute(
                "select source, status from ops.source_status where run_id = %s", [report.run_id]
            )
        }
        raw = conn.execute(
            "select request from raw.market_payloads where run_id = %s and source = 'brapi'",
            [report.run_id],
        ).fetchall()
    assert statuses == {"brapi": "ok", "coingecko": "ok", "tesouro": "ok"}
    assert all("token" not in json.dumps(r["request"]) for r in raw)


def test_segunda_passada_so_busca_o_que_faltou(ingest_pool, admin_url, test_assets):
    calls: list[str] = []
    with mock_client(calls, before_close={"TSTF11"}) as client:
        first = run(ingest_pool, client)
    assert first.pending == ["TSTF11"]
    assert first.status == "partial"

    calls.clear()
    with mock_client(calls) as client:
        second = run(ingest_pool, client, second=True)
    brapi_calls = [c for c in calls if "brapi.dev" in c]
    assert brapi_calls == ["https://brapi.dev/api/quote/TSTF11"]
    assert not [c for c in calls if "coingecko" in c or "tesouro" in c]  # já tinham preço
    assert second.status == "ok"
    assert ("TSTF11", "2030-10-31:BRL:brapi") in prices(admin_url, test_assets)


def test_limite_da_brapi_para_a_fonte_sem_insistir(ingest_pool, test_assets):
    calls: list[str] = []
    with mock_client(calls, brapi_status=429) as client:
        report = run(ingest_pool, client)
    brapi_result = next(s for s in report.sources if s.source == "brapi")
    assert brapi_result.status == "quota_exceeded"
    assert len([c for c in calls if "brapi.dev" in c]) == 1  # parou na primeira recusa
    assert set(report.pending) == {"TSTA3", "TSTF11"}


def test_cota_mensal_conferida_antes_de_chamar(ingest_pool, test_assets):
    calls: list[str] = []
    with mock_client(calls) as client:
        report = run(ingest_pool, client, quota=1)
    assert len([c for c in calls if "brapi.dev" in c]) == 1
    assert next(s for s in report.sources if s.source == "brapi").status == "quota_exceeded"


def test_sem_pregao_a_brapi_nem_e_chamada(ingest_pool, test_assets):
    calls: list[str] = []
    with mock_client(calls) as client:
        report = run_daily(
            ingest_pool,
            day=date(2026, 11, 2),
            second_pass=False,
            client=client,
            brapi_token=None,
            coingecko_key=None,
            tickers=["TSTA3"],
            sources={"brapi"},
            brapi_pause_s=0,
        )
    assert report.sources[0].status == "skipped"
    assert not calls
