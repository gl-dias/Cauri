"""Parsers das fontes de mercado, com amostras reais das respostas (sem rede)."""

import io
import zipfile
from datetime import date
from decimal import Decimal

import httpx
import pytest

from cauri_ingest_market.reference import normalize_alias, sync_aliases
from cauri_ingest_market.sources import bcb_sgs, coingecko, cotahist, tesouro

# Linhas reais do COTAHIST_A2026 (05/01/2026).
PETR4 = (
    "012026010502PETR4       010PETROBRAS   PN  EDJ N2   R$  "
    "000000000307000000000030770000000002973"
    "000000000300800000000030200000000003020000000000302152803000000000048211400000000145060421200"
    "000000000000009999123100000010000000000000BRPETRACNPR6223"
)
HGLG11 = (
    "012026010512HGLG11      010FII HGLG PAXCI  ER       R$  "
    "000000001580700000000158100000000015699"
    "000000001572800000000157350000000015735000000001575623960000000000000094297000000001483161587"
    "000000000000009999123100000010000000000000BRHGLGCTF004291"
)
HEADER = "00COTAHIST.2026BOVESPA 20261028".ljust(245)


class TestCotahist:
    def test_le_acao_do_mercado_a_vista(self):
        quote = cotahist.parse_line(PETR4)
        assert quote is not None
        assert quote.ticker == "PETR4"
        assert quote.trade_date == date(2026, 1, 5)
        assert quote.close == Decimal("30.20")
        assert quote.short_name == "PETROBRAS"
        assert quote.spec == "PN EDJ N2"
        assert quote.isin == "BRPETRACNPR6"

    def test_le_fii(self):
        quote = cotahist.parse_line(HGLG11)
        assert quote is not None
        assert quote.bdi == cotahist.BDI_REITS
        assert quote.close == Decimal("157.35")

    def test_ignora_cabecalho_e_outros_mercados(self):
        assert cotahist.parse_line(HEADER) is None
        fracionario = PETR4[:24] + "020" + PETR4[27:]
        assert cotahist.parse_line(fracionario) is None
        bdr = PETR4[:10] + "34" + PETR4[12:]
        assert cotahist.parse_line(bdr) is None

    def test_fator_de_cotacao_divide_o_preco(self):
        por_mil = PETR4[:210] + "0001000" + PETR4[217:]
        quote = cotahist.parse_line(por_mil)
        assert quote is not None
        assert quote.close == Decimal("0.0302")

    def test_le_do_zip_filtrando_tickers(self, tmp_path):
        path = tmp_path / "COTAHIST_A2026.ZIP"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("COTAHIST_A2026.TXT", "\r\n".join([HEADER, PETR4, HGLG11]).encode("latin-1"))
        assert [q.ticker for q in cotahist.iter_quotes(path)] == ["PETR4", "HGLG11"]
        assert [q.ticker for q in cotahist.iter_quotes(path, {"hglg11"})] == ["HGLG11"]


TESOURO_HEADER = (
    "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
    "PU Compra Manha;PU Venda Manha;PU Base Manha"
)
TESOURO_CSV = (
    TESOURO_HEADER
    + """
Tesouro Selic;01/03/2028;27/10/2026;0,02;0,03;20175,28;20162,27;20162,27
Tesouro IPCA+;15/05/2035;27/10/2026;7,10;7,22;2210,01;2191,45;2191,45
Tesouro IPCA+ com Juros Semestrais;15/08/2060;27/10/2026;;7,05;;4012,34;4012,34
Tesouro Prefixado;01/01/2024;28/12/2023;0,00;0,00;0,00;0,00;0,00
"""
)


class TestTesouro:
    def test_le_o_csv_oficial(self):
        rows = list(tesouro.parse(TESOURO_CSV))
        assert len(rows) == 3  # PU zero (título vencido) fica de fora
        selic = rows[0]
        assert selic.maturity == date(2028, 3, 1)
        assert selic.base_date == date(2026, 10, 27)
        assert selic.pu_base == Decimal("20162.27")
        assert rows[2].pu_buy is None  # sem venda ao investidor nesse dia

    def test_ticker_e_nome_interno(self):
        assert tesouro.ticker_for("Tesouro IPCA+", date(2035, 5, 15)) == "TD-IPCA-15052035"
        assert (
            tesouro.ticker_for("Tesouro IPCA+ com Juros Semestrais", date(2060, 8, 15))
            == "TD-IPCA-JS-15082060"
        )
        assert tesouro.ticker_for("Título que não existe", date(2030, 1, 1)) is None
        assert (
            tesouro.name_for("Tesouro Selic", date(2028, 3, 1)) == "Tesouro Selic 2028 (01/03/2028)"
        )

    def test_cabecalho_errado_e_recusado(self):
        with pytest.raises(ValueError, match="cabeçalho"):
            list(tesouro.parse("a;b;c\n1;2;3\n"))


def test_sgs_le_data_e_valor_sem_float():
    points = bcb_sgs.parse(
        [{"data": "27/10/2026", "valor": "0.050788"}, {"data": "01/09/2026", "valor": "0.82"}]
    )
    assert points == [
        (date(2026, 10, 27), Decimal("0.050788")),
        (date(2026, 9, 1), Decimal("0.82")),
    ]


def test_series_do_bcb_corretas():
    assert (
        bcb_sgs.CDI.code,
        bcb_sgs.SELIC_META.code,
        bcb_sgs.SELIC_EFETIVA.code,
        bcb_sgs.IPCA.code,
        bcb_sgs.PTAX_VENDA.code,
    ) == (
        12,
        432,
        1178,
        433,
        1,  # PTAX de venda; a de compra é a 10813 (conferido na API: a 1 vem sempre maior)
    )


SGS_HTML = "<html><body>The requested URL was rejected.</body></html>"
SGS_JSON = [{"data": "27/10/2026", "valor": "0.050788"}]


def _sgs_client(*responses: httpx.Response) -> tuple[httpx.Client, list[httpx.Request]]:
    """Cliente que devolve as respostas na ordem e guarda os pedidos feitos."""
    queue, requests = list(responses), []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return queue.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def _fetch_cdi(client: httpx.Client, waits: list[float]):
    return bcb_sgs.fetch(
        client, bcb_sgs.CDI, date(2026, 10, 1), date(2026, 10, 28), sleep=waits.append
    )


class TestSgsInstavel:
    def test_html_no_lugar_do_json_tenta_de_novo(self):
        client, requests = _sgs_client(
            httpx.Response(200, text=SGS_HTML, headers={"content-type": "text/html"}),
            httpx.Response(503, text="indisponível"),
            httpx.Response(200, json=SGS_JSON),
        )
        waits: list[float] = []
        points, raw = _fetch_cdi(client, waits)
        assert points == [(date(2026, 10, 27), Decimal("0.050788"))]
        assert len(requests) == 3
        assert waits == list(bcb_sgs.RETRY_WAITS_S)
        assert raw[0]["status"] == 200

    def test_desiste_mostrando_o_que_veio(self):
        client, _ = _sgs_client(
            *[httpx.Response(200, text=SGS_HTML, headers={"content-type": "text/html"})] * 3
        )
        with pytest.raises(bcb_sgs.SgsError) as erro:
            _fetch_cdi(client, [])
        message = str(erro.value)
        assert "CDI (12) de 01/10/2026 a 28/10/2026" in message
        assert "respondeu 200 (text/html)" in message
        assert "The requested URL was rejected" in message

    def test_pedido_errado_nao_repete(self):
        client, requests = _sgs_client(httpx.Response(400, text="data inválida"))
        waits: list[float] = []
        with pytest.raises(httpx.HTTPStatusError):
            _fetch_cdi(client, waits)
        assert (len(requests), waits) == (1, [])

    def test_janela_sem_dados(self):
        client, _ = _sgs_client(httpx.Response(404))
        assert _fetch_cdi(client, []) == (
            [],
            [
                {
                    "params": {
                        "formato": "json",
                        "dataInicial": "01/10/2026",
                        "dataFinal": "28/10/2026",
                    },
                    "status": 404,
                    "data": [],
                }
            ],
        )


def test_coingecko_ponto_das_00h_utc_vira_fechamento_do_dia_anterior_em_brasilia():
    # 2026-10-28T00:00:00Z = 27/10/2026 21:00 em Brasília
    payload = {"prices": [[1793145600000, 426534.12], [1793232000000, 430001.5]]}
    points = coingecko.parse_history(payload)
    assert points == [
        (date(2026, 10, 27), Decimal("426534.12")),
        (date(2026, 10, 28), Decimal("430001.5")),
    ]


class TestApelidos:
    def test_normaliza_acento_caixa_e_espacos(self):
        assert normalize_alias("  Itaú   Unibanco ") == "itau unibanco"
        assert normalize_alias("ITAÚSA") == "itausa"

    def test_mesmo_apelido_para_empresas_diferentes_e_erro(self):
        with pytest.raises(ValueError, match="aponta para ITUB e ITSA"):
            sync_aliases(None, {"ITUB": ["Itaú"], "ITSA": ["itau"]}, {})  # type: ignore[arg-type]


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("COTAHIST_A2026.TXT", f"{HEADER}\n{PETR4}\n")
    return buffer.getvalue()


class _CortaNoMeio(httpx.SyncByteStream):
    """Corpo que entrega um pedaço e cai, como a conexão com a B3 no GitHub Actions."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def __iter__(self):
        yield self.data
        raise httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body"
        )


class TestDownloadCotahist:
    TODAY = date(2026, 10, 29)

    def _download(self, tmp_path, *responses):
        queue, ranges, waits = list(responses), [], []

        def handler(request: httpx.Request) -> httpx.Response:
            ranges.append(request.headers.get("Range"))
            return queue.pop(0)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        path = cotahist.download(2026, tmp_path, client, today=self.TODAY, sleep=waits.append)
        return path, ranges, waits

    def test_continua_de_onde_parou(self, tmp_path):
        data = _zip_bytes()
        half = len(data) // 2
        path, ranges, waits = self._download(
            tmp_path,
            httpx.Response(200, stream=_CortaNoMeio(data[:half])),
            httpx.Response(206, content=data[half:]),
        )
        assert ranges == [None, f"bytes={half}-"]
        assert path.read_bytes() == data
        assert waits == [5.0]
        assert not path.with_suffix(".part").exists()

    def test_servidor_que_ignora_range_manda_tudo_de_novo(self, tmp_path):
        data = _zip_bytes()
        path, _, _ = self._download(
            tmp_path,
            httpx.Response(200, stream=_CortaNoMeio(data[:10])),
            httpx.Response(200, content=data),
        )
        assert path.read_bytes() == data

    def test_desiste_depois_de_quatro_quedas(self, tmp_path):
        data = _zip_bytes()
        cuts = [httpx.Response(200, stream=_CortaNoMeio(data[:5]))] + [
            httpx.Response(206, stream=_CortaNoMeio(data[5:6])) for _ in range(3)
        ]
        with pytest.raises(httpx.RemoteProtocolError):
            self._download(tmp_path, *cuts)
        assert not (tmp_path / "COTAHIST_A2026.ZIP").exists()

    def test_zip_incompleto_nao_vai_para_o_cache(self, tmp_path):
        with pytest.raises(ValueError, match="não é um ZIP completo"):
            self._download(tmp_path, httpx.Response(200, content=_zip_bytes()[:-30]))
        assert list(tmp_path.iterdir()) == []


class TestDownloadTesouro:
    def _client(self, *outcomes):
        queue = list(outcomes)

        def handler(request: httpx.Request) -> httpx.Response:
            outcome = queue.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_tenta_de_novo_em_5xx_e_queda(self):
        waits: list[float] = []
        client = self._client(
            httpx.Response(503),
            httpx.ConnectError("caiu"),
            httpx.Response(200, content=b"Tipo Titulo;Data Vencimento"),
        )
        assert tesouro.download(client, sleep=waits.append).startswith("Tipo Titulo")
        assert waits == [5.0, 15.0]

    def test_desiste_na_terceira(self):
        client = self._client(*[httpx.Response(502)] * 3)
        with pytest.raises(httpx.HTTPStatusError):
            tesouro.download(client, sleep=lambda _: None)

    def test_erro_do_pedido_nao_repete(self):
        client = self._client(httpx.Response(404))
        with pytest.raises(httpx.HTTPStatusError):
            tesouro.download(client, sleep=lambda _: pytest.fail("não devia esperar"))
