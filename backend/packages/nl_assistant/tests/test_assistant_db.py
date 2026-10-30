"""Assistente contra o Postgres local: frases, ambiguidade, cripto e venda descoberta.

Usa o extrator por regras (o Haiku tem os testes de formato com HTTP simulado). Datas de
março de 2011, longe das cotações reais do banco local; "hoje" é 10/03/2011.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

import cauri_nl_assistant as assistant
from cauri_core import MovementType, Origin
from cauri_ledger import Ledger, MovementDraft
from cauri_storage import admin_connection

pytestmark = pytest.mark.db

TODAY = date(2011, 3, 10)
EXTRACTOR = assistant.RuleExtractor()
BROKER = "corretora-teste-a"
ISSUERS = {"PETR": ("PETR3", "PETR4"), "ITUB": ("ITUB3", "ITUB4"), "ITSA": ("ITSA3", "ITSA4")}
ALIASES = {"petrobras": "PETR", "itau": "ITUB", "itausa": "ITSA"}


@pytest.fixture(scope="module")
def market(admin_url, reference_data):
    with admin_connection(admin_url) as conn:
        for code, tickers in ISSUERS.items():
            conn.execute(
                "insert into market.issuers (code, name) values (%s, %s) on conflict do nothing",
                [code, f"Empresa {code}"],
            )
            for ticker in tickers:
                conn.execute(
                    "insert into market.assets (ticker, class, issuer_code, name)"
                    " values (%s, 'acao', %s, %s) on conflict (ticker) do nothing",
                    [ticker, code, f"{code} {ticker[-1]}"],
                )
        for ticker, name in (("BTC", "Bitcoin"), ("USDT", "Tether")):
            conn.execute(
                "insert into market.assets (ticker, class, name) values (%s, 'cripto', %s)"
                " on conflict (ticker) do nothing",
                [ticker, name],
            )
        for alias, code in ALIASES.items():
            conn.execute(
                "insert into market.asset_aliases (alias_norm, issuer_code) values (%s, %s)"
                " on conflict (alias_norm) do nothing",
                [alias, code],
            )
        conn.execute(
            "insert into market.asset_aliases (alias_norm, asset_id)"
            " select 'bitcoin', id from market.assets where ticker = 'BTC'"
            " on conflict (alias_norm) do nothing"
        )
        for ticker in ("PETR3", "PETR4", "ITUB3", "ITUB4", "ITSA4"):
            conn.execute(
                "insert into market.prices_daily (asset_id, price_date, currency, close, source)"
                " select id, date '2011-03-09', 'BRL', 30, 'teste' from market.assets"
                " where ticker = %s on conflict (asset_id, price_date, currency)"
                " do update set close = excluded.close",
                [ticker],
            )
        conn.execute(
            "insert into market.brokers (id, name, kind) values"
            " ('exchange-teste', 'Exchange Teste', 'exchange'),"
            " ('banco-teste', 'Banco Teste', 'banco')"
            " on conflict (id) do nothing"
        )
        for day, value in (("2011-03-09", "1.6700"), ("2011-03-10", "1.6710")):
            conn.execute(
                "insert into market.indicators (series, ref_date, value, unit)"
                " values ('PTAX_VENDA', %s, %s, 'R$/US$') on conflict (series, ref_date)"
                " do update set value = excluded.value",
                [day, value],
            )
    return True


@pytest.fixture
def user(make_user, market):
    return make_user()


def hold(conn, user_id, *positions):
    """Posição inicial (compra manual em 01/03/2011) para a regra de ambiguidade."""
    Ledger(conn).post(
        user_id,
        [
            MovementDraft(
                idempotency_key=f"manual-{uuid4()}",
                trade_date=date(2011, 3, 1),
                type=MovementType.COMPRA,
                broker_id=BROKER,
                ticker=ticker,
                quantity=Decimal(qty),
                unit_price=Decimal(25),
            )
            for ticker, qty in positions
        ],
        origin=Origin.MANUAL,
    )


def say(conn, user_id, text, **kw):
    ledger = Ledger(conn, today=TODAY)
    reply = assistant.send(ledger, user_id, text, extractor=EXTRACTOR, today=TODAY, **kw)
    proposal = (
        ledger.conversations.proposal(user_id, reply.proposal_id) if reply.proposal_id else None
    )
    return reply, proposal


def primaries(proposal):
    return [i for i in proposal.items if i["kind"] != "contrapartida"]


def test_frase_da_especificacao_com_um_ticker_de_cada_empresa(user, as_user):
    with as_user(user) as conn:
        hold(conn, user.id, ("PETR4", 10), ("ITUB4", 5))
        reply, proposal = say(conn, user.id, "comprei 3 petrobras e vendi 2 itau")
        assert reply.text == "Entendi 2 operações. Confira o cartão e confirme."
        petr, itub = proposal.items
        assert (petr["ticker"], petr["draft"]["type"], petr["draft"]["quantity"]) == (
            "PETR4",
            "compra",
            "3",
        )
        assert (itub["ticker"], itub["draft"]["type"]) == ("ITUB4", "venda")
        # Sem preço na frase: fechamento mais recente como sugestão marcada.
        assert petr["price_suggested"] == {"value": "30", "date": "2011-03-09"}
        assert any("sugestão pelo fechamento" in m["text"] for m in petr["messages"])
        assert petr["draft"]["broker_id"] == BROKER
        assert {petr["status"], itub["status"]} == {"ok"}

        confirmed = assistant.confirm(Ledger(conn, today=TODAY), user.id, proposal.id, today=TODAY)
        assert confirmed.status == "confirmed"
        assert all(i["movement_id"] for i in confirmed.items)
        origins = conn.execute(
            "select origin, origin_ref from ledger.movements"
            " where user_id = %s and origin = 'chat'",
            [user.id],
        ).fetchall()
        assert len(origins) == 2
        assert {o["origin_ref"] for o in origins} == {proposal.message_id}
        with pytest.raises(assistant.ProposalClosedError):
            assistant.confirm(Ledger(conn, today=TODAY), user.id, proposal.id, today=TODAY)


def test_ambiguidade_petr3_e_petr4_pergunta_e_a_resposta_resolve(user, as_user):
    with as_user(user) as conn:
        hold(conn, user.id, ("PETR3", 5), ("PETR4", 5))
        reply, proposal = say(conn, user.id, "comprei 1 petrobras a 30")
        [item] = proposal.items
        assert item["status"] == "pergunta"
        assert item["question"]["field"] == "ticker"
        assert item["question"]["options"] == ["PETR3", "PETR4"]
        assert "preciso de uma resposta" in reply.text
        with pytest.raises(assistant.AssistantError, match="pendências"):
            assistant.confirm(Ledger(conn, today=TODAY), user.id, proposal.id, today=TODAY)

        answered = assistant.answer(
            Ledger(conn, today=TODAY),
            user.id,
            proposal.id,
            item["id"],
            "ticker",
            "PETR3",
            today=TODAY,
        )
        [item] = answered.items
        assert (item["status"], item["ticker"]) == ("ok", "PETR3")


def test_itau_nunca_vira_itausa(user, as_user):
    with as_user(user) as conn:
        hold(conn, user.id, ("ITSA4", 10))  # tem Itaúsa, não tem Itaú Unibanco
        _, proposal = say(conn, user.id, "comprei 1 itau a 30")
        [item] = proposal.items
        assert item["status"] == "pergunta"
        assert item["question"]["options"] == ["ITUB3", "ITUB4"]
        _, proposal = say(conn, user.id, "comprei 1 itausa a 10")
        [item] = proposal.items
        assert (item["status"], item["ticker"]) == ("ok", "ITSA4")


def test_bitcoin_em_dolar_pela_ptax_do_dia(user, as_user):
    with as_user(user) as conn:
        hold(conn, user.id, ("PETR4", 1))  # só para haver uma corretora recente
        _, proposal = say(conn, user.id, "comprei 0,01 bitcoin a 120 mil dólares")
        [item] = proposal.items  # dólar não é posição: sem contrapartida
        draft = item["draft"]
        assert item["ticker"] == "BTC"
        assert draft["unit_price"] == "200520"  # 120.000 x PTAX de venda 1,6710 de 10/03
        assert (draft["orig_currency"], draft["orig_value"]) == ("USD", "120000")
        assert (draft["fx_source"], draft["fx_date"]) == ("ptax", "2011-03-10")
        assert any("PTAX de venda de 10/03/2011" in m["text"] for m in item["messages"])


def test_venda_descoberta_oferece_saldo_inicial_e_o_cartao_fecha(user, as_user):
    with as_user(user) as conn:
        hold(conn, user.id, ("PETR4", 10))
        _, proposal = say(conn, user.id, "vendi 100 PETR4 a 31")
        [item] = proposal.items
        assert item["status"] == "erro"
        assert item["messages"][-1]["code"] == "oversell"
        [suggestion] = proposal.suggestions
        assert (suggestion["ticker"], suggestion["quantity"]) == ("PETR4", "90")
        assert suggestion["trade_date"] == "2011-03-09"  # véspera da venda
        assert suggestion["unit_cost"] == "30"  # fechamento do dia, como sugestão

        updated = assistant.add_opening_balance(
            Ledger(conn, today=TODAY),
            user.id,
            proposal.id,
            ticker="PETR4",
            trade_date=date(2011, 3, 9),
            quantity=Decimal(90),
            unit_cost=Decimal(22),
            broker_id=BROKER,
            today=TODAY,
        )
        assert {i["status"] for i in updated.items} == {"ok"}
        assert updated.suggestions == ()
        opening_item = next(i for i in updated.items if i["kind"] == "saldo_inicial")
        assert opening_item["draft"]["opening_balance"] is True
        assistant.confirm(Ledger(conn, today=TODAY), user.id, proposal.id, today=TODAY)


def test_compra_em_usdt_mexe_no_saldo_de_usdt(user, as_user):
    with as_user(user) as conn:
        hold(conn, user.id, ("PETR4", 1))
        _, proposal = say(conn, user.id, "comprei 0,01 bitcoin a 60000 usdt")
        _btc, leg = proposal.items
        assert leg["kind"] == "contrapartida"
        assert (leg["ticker"], leg["draft"]["type"], leg["draft"]["quantity"]) == (
            "USDT",
            "venda",
            "600",
        )
        assert leg["status"] == "erro"  # sem USDT na carteira
        [suggestion] = proposal.suggestions
        assert suggestion["ticker"] == "USDT"


def test_provento_e_edicao_do_cartao(user, as_user):
    with as_user(user) as conn:
        hold(conn, user.id, ("ITUB4", 10))
        _, proposal = say(conn, user.id, "recebi 50 reais de dividendos do itau")
        [item] = proposal.items
        assert item["draft"]["type"] == "provento"
        assert (item["draft"]["amount"], item["draft"]["income_kind"]) == ("50", "dividendo")

        _, proposal = say(conn, user.id, "comprei 2 PETR4")
        [item] = proposal.items
        edited = assistant.edit(
            Ledger(conn, today=TODAY),
            user.id,
            proposal.id,
            item["id"],
            {"preco": "29.5", "data": "2011-03-08"},
            today=TODAY,
        )
        [item] = edited.items
        assert item["price_suggested"] is None
        assert (item["draft"]["unit_price"], item["draft"]["trade_date"]) == ("29.5", "2011-03-08")


def test_pergunta_de_corretora_traz_todas_e_exchange_so_em_cripto(user, as_user):
    with as_user(user) as conn:
        _, proposal = say(conn, user.id, "comprei 2 PETR4 a 30 e comprei 0,01 BTC a 9 mil reais")
        acao, btc = primaries(proposal)
        kinds = Ledger(conn).broker_kinds()
        for item in (acao, btc):
            assert (item["status"], item["question"]["field"]) == ("pergunta", "broker_id")
        acao_options, btc_options = acao["question"]["options"], btc["question"]["options"]
        assert {kinds[b] for b in acao_options} == {"corretora", "banco"}
        assert len(acao_options) == sum(k != "exchange" for k in kinds.values())
        assert acao_options.index(BROKER) < acao_options.index("banco-teste")
        assert len(btc_options) == len(kinds)
        assert kinds[btc_options[0]] == "exchange"


def test_frase_sem_operacao_e_conversa_de_outro_usuario(user, make_user, as_user):
    with as_user(user) as conn:
        reply, proposal = say(conn, user.id, "bom dia")
        assert proposal is None
        assert "Não encontrei nenhuma operação" in reply.text
        stored = conn.execute(
            "select llm_output from assistant.messages where user_id = %s and role = 'user'",
            [user.id],
        ).fetchone()
        assert stored["llm_output"] == {"operacoes": []}
        _, proposal = say(conn, user.id, "comprei 1 PETR4 a 30")
    other = make_user()
    with as_user(other) as conn:
        assert Ledger(conn).conversations.recent(other.id) == []
        with pytest.raises(assistant.ProposalNotFoundError):
            assistant.confirm(Ledger(conn, today=TODAY), other.id, proposal.id, today=TODAY)


class BrokenExtractor:
    model = "claude-haiku-5-5"

    def extract(self, text, today):
        raise assistant.ExtractionError("O assistente não respondeu agora. Tente de novo.")


class CountingExtractor:
    model = "claude-haiku-5-5"

    def extract(self, text, today):
        result = assistant.RuleExtractor().extract(text, today)
        return assistant.Extraction(result.ops, self.model, input_tokens=812, output_tokens=95)


def usage(conn, user_id):
    return conn.execute(
        "select provider, kind, model, input_tokens, output_tokens, ok from ops.llm_usage"
        " where user_id = %s order by id",
        [user_id],
    ).fetchall()


def test_limite_diario_e_registro_de_tokens(user, as_user):
    with as_user(user) as conn:
        ledger = Ledger(conn, today=TODAY)
        for _ in range(2):
            assistant.send(
                ledger, user.id, "comprei 1 PETR4 a 30", extractor=CountingExtractor(),
                today=TODAY, daily_limit=2,
            )  # fmt: skip
        with pytest.raises(assistant.LimitReachedError, match="limite de 2 mensagens"):
            assistant.send(
                ledger, user.id, "comprei 1 PETR4 a 30", extractor=CountingExtractor(),
                today=TODAY, daily_limit=2,
            )  # fmt: skip
        rows = usage(conn, user.id)
        assert len(rows) == 2
        assert rows[0]["input_tokens"] == 812
        assert rows[0]["output_tokens"] == 95
        assert (rows[0]["provider"], rows[0]["kind"], rows[0]["ok"]) == (
            "anthropic",
            "mensagem",
            True,
        )


def test_falha_do_modelo_vira_resposta_e_conta_no_uso(user, as_user):
    with as_user(user) as conn:
        reply = assistant.send(
            Ledger(conn, today=TODAY), user.id, "comprei 1 PETR4", extractor=BrokenExtractor(),
            today=TODAY,
        )  # fmt: skip
        assert reply.proposal_id is None
        assert "não respondeu" in reply.text
        [row] = usage(conn, user.id)
        assert row["ok"] is False


def test_frase_longa_demais_nem_chega_ao_modelo(user, as_user):
    with as_user(user) as conn, pytest.raises(assistant.AssistantError, match="longa demais"):
        assistant.send(
            Ledger(conn, today=TODAY), user.id, "comprei 1 PETR4 " * 40,
            extractor=BrokenExtractor(), today=TODAY,
        )  # fmt: skip
