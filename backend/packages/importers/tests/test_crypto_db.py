"""Cripto e perfis de colunas contra o Postgres local, com o RLS do usuário.

Datas de março de 2011, longe de qualquer cotação real do banco local. A PTAX e os
fechamentos são inseridos aqui; 05 e 06/03 são fim de semana e 07 e 08/03 foram Carnaval.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

import cauri_importers as importers
from cauri_core import MovementType, Origin
from cauri_importers import Upload
from cauri_ledger import Ledger, MovementDraft
from cauri_storage import admin_connection

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).parent / "fixtures"
PTAX = {
    date(2011, 3, 1): "1.6550",
    date(2011, 3, 2): "1.6600",
    date(2011, 3, 3): "1.6620",
    date(2011, 3, 4): "1.6650",
    date(2011, 3, 9): "1.6700",
}
CLOSES = {
    "TSTCOIN": {date(2011, 3, d): str(320 + 10 * (d - 1)) for d in range(1, 11)},  # 320, 330...
    "TSTFEE": {date(2011, 3, d): "2.5" for d in range(1, 11)},
}


@pytest.fixture(scope="module")
def market_2011(admin_url, reference_data):
    with admin_connection(admin_url) as conn:
        for ticker, name in (("USDT", "Tether"), ("TSTFEE", "Moeda de taxa de teste")):
            conn.execute(
                "insert into market.assets (ticker, class, name) values (%s, 'cripto', %s)"
                " on conflict (ticker) do nothing",
                [ticker, name],
            )
        for day, value in PTAX.items():
            conn.execute(
                "insert into market.indicators (series, ref_date, value, unit)"
                " values ('PTAX_VENDA', %s, %s, 'R$/US$')"
                " on conflict (series, ref_date) do update set value = excluded.value",
                [day, value],
            )
        for ticker, closes in CLOSES.items():
            for day, value in closes.items():
                conn.execute(
                    "insert into market.prices_daily"
                    " (asset_id, price_date, currency, close, source)"
                    " select id, %s, 'BRL', %s, 'teste' from market.assets where ticker = %s"
                    " on conflict (asset_id, price_date, currency)"
                    " do update set close = excluded.close",
                    [day, value, ticker],
                )
    return True


@pytest.fixture
def user(make_user, market_2011):
    return make_user()


def fund(conn, user_id):
    """Saldo inicial de USDT e da moeda de taxa, para as contrapartidas não ficarem descobertas."""
    Ledger(conn).post(
        user_id,
        [
            MovementDraft(
                idempotency_key=f"manual-{uuid4()}",
                trade_date=date(2011, 3, 1),
                type=MovementType.COMPRA,
                broker_id="binance-teste",
                ticker=ticker,
                quantity=Decimal(qty),
                unit_price=Decimal(price),
            )
            for ticker, qty, price in (("USDT", "1000", "1.66"), ("TSTFEE", "10", "2.5"))
        ],
        origin=Origin.MANUAL,
    )


@pytest.fixture(autouse=True)
def binance_broker(admin_url):
    # A exchange de teste tem o nome "Binance": o adaptador manda "binance" e o cadastro
    # resolve pelo nome. No banco local a Binance real também existe e fica com o id real.
    with admin_connection(admin_url) as conn:
        conn.execute(
            "insert into market.brokers (id, name, kind) values ('binance-teste', 'Binance Teste',"
            " 'exchange') on conflict (id) do nothing"
        )
        row = conn.execute("select id from market.brokers where name = 'Binance'").fetchone()
        if row is None:
            conn.execute(
                "insert into market.brokers (id, name, kind) values ('binance', 'Binance',"
                " 'exchange')"
            )


def upload(name):
    return Upload(name, (FIXTURES / name).read_bytes())


def rows_of(preview):
    return [r for f in preview.batch.files for r in f.rows]


def test_trades_da_binance_em_reais_com_moeda_original(user, as_user):
    with as_user(user) as conn:
        fund(conn, user.id)
        preview = importers.preview(Ledger(conn), user.id, [upload("binance-trades.csv")])
        rows = rows_of(preview)
        assert [r.status for r in rows] == ["ok"] * len(rows), [r.messages for r in rows]

        buy = rows[0].draft
        assert buy["ticker"] == "TSTCOIN"
        assert buy["quantity"] == "0.4995"
        assert buy["unit_price"] == "332"  # 200 USDT x PTAX 1,66 de 02/03
        assert buy["fees"] == "0.17"
        assert (buy["orig_currency"], buy["orig_value"]) == ("USDT", "200")
        assert (buy["fx_rate"], buy["fx_date"], buy["fx_source"]) == ("1.66", "2011-03-02", "ptax")
        assert (buy["fee_asset"], buy["fee_quantity"]) == ("TSTCOIN", "0.0005")
        assert "PTAX de venda de 02/03/2011" in rows[0].messages[0]["text"]

        # Taxa em terceiro ativo: 0,1 TSTFEE a R$ 2,50 vira R$ 0,25 de custo e uma venda.
        third = rows[2].draft
        assert third["fees"] == "0.25"
        assert (third["fee_asset"], third["fee_quantity"]) == ("TSTFEE", "0.1")
        assert rows[4].draft["ticker"] == "TSTFEE"
        assert rows[4].draft["type"] == "venda"

        # Sábado: vale a PTAX de sexta (04/03), e a linha avisa.
        weekend = rows[5]
        assert weekend.draft["fx_date"] == "2011-03-04"
        assert weekend.draft["unit_price"] == "349.65"
        assert any("última antes da data" in m["text"] for m in weekend.messages)

        # Par em reais: sem conversão.
        brl = rows[7].draft
        assert brl["orig_currency"] is None
        assert brl["unit_price"] == "350"

        # Par cotado em outra cripto: fechamento do TSTCOIN em 04/03 (R$ 350).
        cross = rows[8].draft
        assert cross["fx_source"] == "fechamento"
        assert cross["unit_price"] == "3.5"

        importers.commit(Ledger(conn), user.id, preview.batch.id, {})
        saved = conn.execute(
            "select orig_currency, orig_value, fx_rate, fx_date, fx_source, fee_asset, fee_quantity"
            " from ledger.movements where user_id = %s and idempotency_key = %s",
            [user.id, rows[0].idempotency_key],
        ).fetchone()
        assert saved["orig_currency"] == "USDT"
        assert saved["fx_date"] == date(2011, 3, 2)
        assert saved["fee_asset"] == "TSTCOIN"


def test_recompensas_de_earn_viram_provento_e_entram_no_saldo(user, as_user):
    with as_user(user) as conn:
        preview = importers.preview(Ledger(conn), user.id, [upload("binance-extrato.csv")])
        rows = rows_of(preview)
        income, bought = rows[0], rows[1]
        assert income.draft["type"] == "provento"
        assert income.draft["amount"] == "3.3"  # 0,01 x fechamento de 02/03 (R$ 330)
        assert bought.draft["type"] == "compra"
        assert bought.draft["unit_price"] == "330"
        # Recompensa de USDT de menos de 1 centavo: só a quantidade entra.
        tiny = [r for r in rows if r.line_numbers == (8,)]
        assert tiny[0].status == "ignored"
        assert "1 centavo" in tiny[0].messages[0]["text"]
        assert tiny[1].draft["ticker"] == "USDT"
        assert tiny[1].status == "ok"
        assert any("trades" in w for w in preview.batch.warnings)


def test_reenviar_trades_da_binance_nao_duplica(user, as_user):
    with as_user(user) as conn:
        fund(conn, user.id)
        first = importers.preview(Ledger(conn), user.id, [upload("binance-trades.csv")])
        importers.commit(Ledger(conn), user.id, first.batch.id, {})
        again = importers.preview(Ledger(conn), user.id, [upload("binance-trades.csv")])
        assert {r.status for r in rows_of(again)} == {"already_imported"}


def test_arquivo_desconhecido_vira_perfil_e_e_reconhecido_depois(user, make_user, as_user):
    unknown = upload("corretora-desconhecida.csv")
    with as_user(user) as conn:
        first = importers.preview(Ledger(conn), user.id, [unknown])
        assert first.batch is None
        [problem] = first.problems
        assert problem.columns == (
            "Data Operação", "Operação", "Papel", "Qtde", "Preço", "Valor Total", "Corretagem",
        )  # fmt: skip

        profile_id = Ledger(conn).imports.save_profile(
            user.id,
            "Corretora Fictícia",
            {
                "data": "Data Operação",
                "tipo": "Operação",
                "ativo": "Papel",
                "quantidade": "Qtde",
                "preco": "Preço",
                "valor": "Valor Total",
                "taxa": "Corretagem",
            },
            {"broker_id": "corretora-teste-a", "decimal": ",", "date_format": "dd/mm/aaaa"},
        )
        second = importers.preview(Ledger(conn), user.id, [unknown])
        [file] = second.batch.files
        assert file.adapter == f"perfil-{str(profile_id)[:8]}"
        assert file.label.startswith("Perfil Corretora Fictícia")
        assert [r.status for r in file.rows] == ["ok", "ok", "ok"]
        assert file.rows[0].draft["fees"] == "1"
        [profile] = Ledger(conn).imports.profiles(user.id)
        assert profile.last_used_at is not None
        importers.commit(Ledger(conn), user.id, second.batch.id, {})
        label = conn.execute(
            "select distinct origin_label from ledger.movements where user_id = %s", [user.id]
        ).fetchone()["origin_label"]
        assert label == "Corretora Fictícia"

    other = make_user()
    with as_user(other) as conn:
        assert Ledger(conn).imports.profiles(other.id) == []
        assert importers.preview(Ledger(conn), other.id, [unknown]).batch is None


def test_perfil_nunca_guarda_cpf(user, as_user):
    import psycopg

    with as_user(user) as conn, pytest.raises(psycopg.errors.CheckViolation):
        Ledger(conn).imports.save_profile(user.id, "X", {"data": "123.456.789-00"}, {})


def test_deposito_externo_de_usdt_e_compra_sem_historico(user, as_user):
    """O caso do saldo que falta: USDT depositado de fora, compra de TSTCOIN paga com esse
    USDT e nenhum histórico anterior. A contrapartida em USDT fica descoberta; a prévia
    sugere o saldo inicial na data do depósito, com a PTAX do dia como custo sugerido, e o
    depósito avisa que explica o saldo. Incluir o saldo resolve sem reenviar os arquivos."""
    files = [upload("binance-deposito-usdt.csv"), upload("binance-trades-usdt.csv")]
    with as_user(user) as conn:
        preview = importers.preview(Ledger(conn), user.id, files)
        deposit_file, trades_file = preview.batch.files
        buy, usdt_leg = trades_file.rows
        assert buy.status == "ok"
        assert usdt_leg.status == "error"
        assert usdt_leg.messages[0]["code"] == "oversell"

        [suggestion] = preview.batch.suggestions
        assert suggestion["ticker"] == "USDT"
        assert suggestion["trade_date"] == "2011-03-01"  # o dia do depósito
        assert suggestion["quantity"] == "150"  # o depósito todo, não só o que faltou
        assert suggestion["first_shortfall"] == "2011-03-02"
        assert suggestion["unit_cost"] == "1.655"  # PTAX de venda de 01/03
        assert "sugestão: PTAX de venda de 01/03/2011" in suggestion["cost_note"]
        assert suggestion["deposit"] == {"quantity": "150", "day": "2011-03-01"}
        [deposit] = deposit_file.rows
        assert deposit.status == "ignored"
        assert any("explica o saldo de USDT" in m["text"] for m in deposit.messages)

        batch = importers.add_opening_balance(
            Ledger(conn),
            user.id,
            preview.batch.id,
            ticker="USDT",
            trade_date=date(2011, 3, 1),
            quantity=Decimal(150),
            unit_cost=Decimal("1.60"),  # o custo que o usuário pagou, não a sugestão
            broker_id="binance",
        )
        rows = {f.adapter: f.rows for f in batch.files}
        assert [r.status for r in rows["binance-trades"]] == ["ok", "ok"]
        assert [r.status for r in rows["saldo-inicial"]] == ["ok"]
        assert batch.suggestions == ()
        assert not any("explica" in m["text"] for m in rows["binance-transferencias"][0].messages)

        importers.commit(Ledger(conn), user.id, batch.id, {})
        saved = conn.execute(
            "select a.ticker, m.type, m.quantity, m.unit_price, m.opening_balance, m.origin_label"
            " from ledger.movements m join market.assets a on a.id = m.asset_id"
            " where m.user_id = %s order by m.trade_date, m.opening_balance desc, a.ticker",
            [user.id],
        ).fetchall()
        opening_row = saved[0]
        assert (opening_row["ticker"], opening_row["quantity"]) == ("USDT", Decimal(150))
        assert opening_row["opening_balance"] is True
        assert opening_row["origin_label"] == "Saldo inicial"
        assert opening_row["unit_price"] == Decimal("1.60")
        usdt = sum(
            r["quantity"] if r["type"] == "compra" else -r["quantity"]
            for r in saved
            if r["ticker"] == "USDT"
        )
        assert usdt == Decimal("49.9")  # 150 - 100 - 0,1 de taxa

    with as_user(user) as conn:
        again = importers.preview(Ledger(conn), user.id, files)
        assert again.batch.suggestions == ()
        assert {r.status for f in again.batch.files for r in f.rows} == {
            "ignored",
            "already_imported",
        }


def test_venda_descoberta_sem_deposito_sugere_a_vespera(user, as_user):
    with as_user(user) as conn:
        preview = importers.preview(Ledger(conn), user.id, [upload("binance-trades-usdt.csv")])
        [suggestion] = preview.batch.suggestions
        assert suggestion["trade_date"] == "2011-03-01"  # véspera da compra de 02/03
        assert suggestion["quantity"] == "100.1"  # o que faltou, com a taxa
        assert suggestion["deposit"] is None


def test_p2p_e_a_entrada_de_usdt_que_cobre_a_compra(user, as_user):
    files = [upload("binance-p2p.csv"), upload("binance-trades-usdt.csv")]
    with as_user(user) as conn:
        preview = importers.preview(Ledger(conn), user.id, files)
        statuses = [r.status for f in preview.batch.files for r in f.rows]
        assert statuses == ["ok", "ok", "ignored", "ok", "ok"]
        assert preview.batch.suggestions == ()
