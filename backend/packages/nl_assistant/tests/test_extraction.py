"""Extração (regras e Haiku com HTTP simulado) e transcrição, sem banco."""

import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from cauri_nl_assistant import (
    AnthropicExtractor,
    ExtractionError,
    GroqTranscriber,
    RuleExtractor,
    SpokenOp,
    TranscriptionError,
)
from cauri_nl_assistant.extraction import TOOL_NAME

TODAY = date(2011, 3, 10)


def extract(text):
    return RuleExtractor().extract(text, TODAY).ops


class TestRegras:
    def test_frase_da_especificacao(self):
        assert extract("comprei 3 petrobras e vendi 2 itau") == (
            SpokenOp("compra", "petrobras", Decimal(3)),
            SpokenOp("venda", "itau", Decimal(2)),
        )

    def test_cripto_em_dolar_com_mil(self):
        [op] = extract("Comprei 0,01 bitcoin a 120 mil dólares")
        assert op == SpokenOp("compra", "bitcoin", Decimal("0.01"), Decimal(120000), "USD")

    def test_preco_em_reais_e_data_relativa(self):
        [op] = extract("comprei 10 PETR4 a 38,45 ontem")
        assert (op.ativo, op.quantidade, op.preco, op.data) == (
            "petr4",
            Decimal(10),
            Decimal("38.45"),
            date(2011, 3, 9),
        )

    def test_provento_com_valor_total(self):
        [op] = extract("recebi 50 reais de dividendos do itau")
        assert op == SpokenOp("provento", "itau", None, Decimal(50), "BRL")

    def test_saldo_inicial_e_data_explicita(self):
        [op] = extract("tinha 150 usdt a 5,30 em 01/03/2011")
        assert (op.tipo, op.ativo, op.quantidade, op.preco, op.data) == (
            "saldo_inicial",
            "usdt",
            Decimal(150),
            Decimal("5.30"),
            date(2011, 3, 1),
        )

    def test_frase_sem_operacao(self):
        assert extract("bom dia, como vai a carteira?") == ()


def anthropic_response(ops):
    return {
        "content": [
            {"type": "text", "text": "ok"},
            {"type": "tool_use", "name": TOOL_NAME, "input": {"operacoes": ops}},
        ]
    }


class TestHaiku:
    def test_pedido_leva_so_a_frase_e_a_data_e_forca_a_ferramenta(self):
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            seen["headers"] = request.headers
            return httpx.Response(200, json=anthropic_response([]))

        extractor = AnthropicExtractor(
            "chave-de-teste", client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        extractor.extract("comprei 3 petrobras", TODAY)
        body = seen["body"]
        assert body["model"] == "claude-haiku-5-5"
        assert body["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
        assert body["messages"] == [{"role": "user", "content": "comprei 3 petrobras"}]
        assert "2011-03-10" in body["system"]
        assert seen["headers"]["x-api-key"] == "chave-de-teste"
        # Nada além da frase e da data: nenhuma carteira, ticker ou valor do usuário.
        assert set(body) == {"model", "max_tokens", "system", "messages", "tools", "tool_choice"}

    def test_resposta_vira_operacoes_com_decimal(self):
        ops = [
            {
                "tipo": "compra",
                "ativo": "bitcoin",
                "quantidade": "0.01",
                "preco": "120000",
                "moeda": "dólares",
                "data": None,
            },
            {
                "tipo": "venda",
                "ativo": "itau",
                "quantidade": 2,
                "preco": None,
                "moeda": None,
                "data": "2011-03-09",
            },
        ]
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json=anthropic_response(ops))
            )
        )
        result = AnthropicExtractor("k", client=client).extract("x", TODAY)
        assert result.ops[0] == SpokenOp(
            "compra", "bitcoin", Decimal("0.01"), Decimal(120000), "USD"
        )
        assert result.ops[1].quantidade == Decimal(2)
        assert result.ops[1].data == date(2011, 3, 9)
        assert isinstance(result.ops[0].quantidade, Decimal)

    def test_sobrecarga_tenta_de_novo_uma_vez(self):
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(529, json={})
            return httpx.Response(200, json=anthropic_response([]))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        AnthropicExtractor("k", client=client).extract("x", TODAY)
        assert len(calls) == 2

    def test_erro_vira_mensagem_amigavel(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
        with pytest.raises(ExtractionError, match="não respondeu"):
            AnthropicExtractor("k", client=client).extract("x", TODAY)


class TestTranscricao:
    def test_groq_recebe_o_audio_e_devolve_o_texto(self):
        seen = {}

        def handler(request):
            seen["body"] = request.content
            seen["auth"] = request.headers["authorization"]
            return httpx.Response(200, json={"text": " comprei 3 petrobras "})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        text = GroqTranscriber("chave", client=client).transcribe(
            b"audio", "fala.webm", "audio/webm"
        )
        assert text == "comprei 3 petrobras"
        assert seen["auth"] == "Bearer chave"
        assert b"whisper-large-v3-turbo" in seen["body"]
        assert b'name="language"' in seen["body"]

    def test_audio_vazio_ou_falha(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        with pytest.raises(TranscriptionError):
            GroqTranscriber("k", client=client).transcribe(b"", "a.webm", "audio/webm")
        with pytest.raises(TranscriptionError):
            GroqTranscriber("k", client=client).transcribe(b"x", "a.webm", "audio/webm")
