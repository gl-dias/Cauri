"""brapi: fechamento conferido pelo horário, cota sem nova tentativa, token só no header."""

from datetime import date
from decimal import Decimal

import httpx

from cauri_ingest_market.sources import brapi
from cauri_ingest_market.sources.brapi import QuoteOutcome

FRI_DST = date(2026, 10, 30)  # com horário de verão americano: fecha às 17h
TUE_STD = date(2026, 11, 3)  # sem horário de verão americano: fecha às 18h


def payload(price: float, when: str, symbol: str = "PETR4") -> dict:
    return {
        "results": [
            {
                "symbol": symbol,
                "regularMarketPrice": price,
                "regularMarketTime": when,
                "currency": "BRL",
            }
        ]
    }


class TestFechamentoPeloHorario:
    def test_cotacao_depois_do_call_e_fechamento(self):
        quote = brapi.parse_quote(
            "PETR4", payload(38.45, "2026-10-30T20:02:00.000Z"), FRI_DST
        )  # 17h02
        assert quote.outcome is QuoteOutcome.CLOSE
        assert quote.price == Decimal("38.45")

    def test_mesmo_horario_em_novembro_ainda_nao_e_fechamento(self):
        # 17h45 em Brasília: com o fim do horário de verão americano, o call só começa às 17h55.
        quote = brapi.parse_quote("PETR4", payload(38.45, "2026-11-03T20:45:00.000Z"), TUE_STD)
        assert quote.outcome is QuoteOutcome.NOT_CLOSED_YET

    def test_em_novembro_fechamento_so_depois_das_17h55(self):
        quote = brapi.parse_quote(
            "PETR4", payload(38.5, "2026-11-03T21:00:30.000Z"), TUE_STD
        )  # 18h00
        assert quote.outcome is QuoteOutcome.CLOSE

    def test_cotacao_de_outro_dia_nao_vira_fechamento_de_hoje(self):
        quote = brapi.parse_quote(
            "HGLG11", payload(157.1, "2026-10-29T20:00:00.000Z", "HGLG11"), FRI_DST
        )
        assert quote.outcome is QuoteOutcome.STALE

    def test_ticker_ausente_na_resposta(self):
        assert (
            brapi.parse_quote("PETR4", {"results": []}, FRI_DST).outcome is QuoteOutcome.NOT_FOUND
        )


def client_with(*responses: httpx.Response, seen: list[httpx.Request]) -> httpx.Client:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_limite_atingido_para_sem_nova_tentativa():
    seen: list[httpx.Request] = []
    with client_with(httpx.Response(429, json={"message": "limite"}), seen=seen) as client:
        quote = brapi.fetch_quote(client, "PETR4", "token-de-teste", FRI_DST)
    assert quote.outcome is QuoteOutcome.QUOTA
    assert len(seen) == 1


def test_erro_5xx_tem_uma_nova_tentativa_so():
    seen: list[httpx.Request] = []
    with client_with(httpx.Response(502), httpx.Response(503), seen=seen) as client:
        quote = brapi.fetch_quote(client, "PETR4", None, FRI_DST)
    assert quote.outcome is QuoteOutcome.ERROR
    assert len(seen) == 2


def test_erro_5xx_seguido_de_sucesso():
    seen: list[httpx.Request] = []
    ok = httpx.Response(200, json=payload(38.45, "2026-10-30T20:02:00.000Z"))
    with client_with(httpx.Response(500), ok, seen=seen) as client:
        quote = brapi.fetch_quote(client, "PETR4", "token-de-teste", FRI_DST)
    assert quote.outcome is QuoteOutcome.CLOSE


def test_token_vai_no_header_e_nunca_na_url():
    seen: list[httpx.Request] = []
    ok = httpx.Response(200, json=payload(38.45, "2026-10-30T20:02:00.000Z"))
    with client_with(ok, seen=seen) as client:
        brapi.fetch_quote(client, "PETR4", "token-de-teste", FRI_DST)
    assert seen[0].headers["Authorization"] == "Bearer token-de-teste"
    assert "token" not in str(seen[0].url)
