"""Pré-visualização e gravação contra o Postgres local, com o RLS do usuário."""

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

HEADER = "data;tipo;ativo;classe;quantidade;preco;taxas;valor;corretora;tipo_provento;obs"
BROKER = "Corretora Teste A"


def csv(*lines: str) -> Upload:
    return Upload("movimentacoes.csv", "\n".join([HEADER, *lines]).encode())


BUY = "05/01/2026;compra;TSTA3;acao;100;20,00;1,50;;Corretora Teste A;;"
BUY_2 = "06/01/2026;compra;TSTA3;acao;50;21,00;;;Corretora Teste A;;"
SELL = "20/01/2026;venda;TSTA3;acao;30;25,00;;;Corretora Teste A;;"
INCOME = "15/01/2026;provento;TSTF11;fii;;;;12,34;corretora-teste-b;;"


@pytest.fixture
def user(make_user, reference_data):
    return make_user()


def statuses(preview):
    return [r.status for f in preview.batch.files for r in f.rows]


def rows(preview):
    return [r for f in preview.batch.files for r in f.rows]


def movements(conn, user_id):
    return conn.execute(
        "select type, quantity, amount, origin, origin_label, origin_ref, voided_at, void_reason,"
        " idempotency_key, fees from ledger.movements where user_id = %s order by created_at, id",
        [user_id],
    ).fetchall()


def test_previa_nao_grava_nada_e_commit_grava_com_origem_do_lote(user, as_user):
    with as_user(user) as conn:
        preview = importers.preview(Ledger(conn), user.id, [csv(BUY, INCOME, SELL)])
        assert statuses(preview) == ["ok", "ok", "ok"]
        assert movements(conn, user.id) == []
        assert preview.batch.files[0].label == "Template do Cauri, 01/2026 a 01/2026"
        batch_id = preview.batch.id

    with as_user(user) as conn:
        result = importers.commit(Ledger(conn), user.id, batch_id, {})
        assert result.created == 3
        saved = movements(conn, user.id)
        assert sorted(m["type"] for m in saved) == ["compra", "provento", "venda"]
        assert {m["origin"] for m in saved} == {"import"}
        assert {m["origin_label"] for m in saved} == {"Planilha"}
        assert {m["origin_ref"] for m in saved} == {batch_id}
        assert {m["fees"] for m in saved} == {Decimal("1.50"), Decimal(0)}
        assert all(m["idempotency_key"].startswith("imp:planilha:") for m in saved)
        stored = Ledger(conn).imports.batch(user.id, batch_id)
        assert stored.status == "committed"
        assert all(r.movement_id for r in stored.files[0].rows)


def test_reenviar_o_mesmo_arquivo_nao_duplica(user, as_user):
    with as_user(user) as conn:
        first = importers.preview(Ledger(conn), user.id, [csv(BUY, INCOME)])
        importers.commit(Ledger(conn), user.id, first.batch.id, {})
    with as_user(user) as conn:
        again = importers.preview(Ledger(conn), user.id, [csv(BUY, INCOME)])
        assert statuses(again) == ["already_imported", "already_imported"]
        result = importers.commit(Ledger(conn), user.id, again.batch.id, {})
        assert result.created == 0
        assert len(movements(conn, user.id)) == 2


def test_export_com_periodo_sobreposto_so_traz_o_que_e_novo(user, as_user):
    with as_user(user) as conn:
        first = importers.preview(Ledger(conn), user.id, [csv(BUY, INCOME)])
        importers.commit(Ledger(conn), user.id, first.batch.id, {})
    with as_user(user) as conn:
        overlapping = importers.preview(Ledger(conn), user.id, [csv(INCOME, BUY_2, SELL)])
        assert statuses(overlapping) == ["already_imported", "ok", "ok"]
        importers.commit(Ledger(conn), user.id, overlapping.batch.id, {})
        assert sorted(m["type"] for m in movements(conn, user.id)) == [
            "compra",
            "compra",
            "provento",
            "venda",
        ]


def test_duas_compras_identicas_no_mesmo_dia_continuam_sendo_duas(user, as_user):
    with as_user(user) as conn:
        preview = importers.preview(Ledger(conn), user.id, [csv(BUY, BUY)])
        assert statuses(preview) == ["ok", "ok"]
        importers.commit(Ledger(conn), user.id, preview.batch.id, {})
        assert len(movements(conn, user.id)) == 2
    with as_user(user) as conn:
        again = importers.preview(Ledger(conn), user.id, [csv(BUY, BUY, BUY)])
        assert statuses(again) == ["already_imported", "already_imported", "ok"]


def test_linhas_com_erro_nao_travam_as_boas(user, as_user):
    bad_broker = "07/01/2026;compra;TSTA3;acao;1;20,00;;;Corretora Inexistente;;"
    bad_asset = "07/01/2026;compra;NAOEXISTE3;acao;1;20,00;;;Corretora Teste A;;"
    oversell = "08/01/2026;venda;TSTB4;acao;10;20,00;;;Corretora Teste A;;"
    with as_user(user) as conn:
        preview = importers.preview(
            Ledger(conn), user.id, [csv(BUY, bad_broker, bad_asset, oversell)]
        )
        found = rows(preview)
        assert [r.status for r in found] == ["ok", "error", "error", "error"]
        assert "Corretora não reconhecida" in found[1].messages[0]["text"]
        assert "Ativo não encontrado: NAOEXISTE3" in found[2].messages[0]["text"]
        assert "Venda maior que a posição" in found[3].messages[0]["text"]
        result = importers.commit(Ledger(conn), user.id, preview.batch.id, {})
        assert result.created == 1


def manual_buy(conn, user_id, quantity="100", day=date(2026, 1, 5)):
    Ledger(conn).post(
        user_id,
        [
            MovementDraft(
                idempotency_key=f"manual-{uuid4()}",
                trade_date=day,
                type=MovementType.COMPRA,
                broker_id="corretora-teste-a",
                ticker="TSTA3",
                quantity=Decimal(quantity),
                unit_price=Decimal(20),
            )
        ],
        origin=Origin.MANUAL,
    )


def test_duplicado_de_lancamento_manual_por_padrao_mantem_o_existente(user, as_user):
    with as_user(user) as conn:
        manual_buy(conn, user.id)
        preview = importers.preview(Ledger(conn), user.id, [csv(BUY)])
        [row] = rows(preview)
        assert row.status == "possible_duplicate"
        assert row.decision == "keep_existing"
        assert "Manual" in row.messages[0]["text"]
        result = importers.commit(Ledger(conn), user.id, preview.batch.id, {})
        assert (result.created, result.skipped) == (0, 1)
        assert [m["origin"] for m in movements(conn, user.id)] == ["manual"]


def test_substituir_pela_planilha_remove_o_manual_com_motivo(user, as_user):
    with as_user(user) as conn:
        manual_buy(conn, user.id)
        preview = importers.preview(Ledger(conn), user.id, [csv(BUY)])
        [row] = rows(preview)
        result = importers.commit(Ledger(conn), user.id, preview.batch.id, {row.id: "replace"})
        assert (result.created, result.replaced) == (1, 1)
        imported, manual = sorted(movements(conn, user.id), key=lambda m: m["origin"])
        assert manual["origin"] == "manual"
        assert manual["voided_at"] is not None
        assert "importação" in manual["void_reason"]
        assert imported["origin"] == "import"
        assert imported["voided_at"] is None


def test_importar_como_nova_mantem_os_dois(user, as_user):
    with as_user(user) as conn:
        manual_buy(conn, user.id)
        preview = importers.preview(Ledger(conn), user.id, [csv(BUY)])
        [row] = rows(preview)
        importers.commit(Ledger(conn), user.id, preview.batch.id, {row.id: "import_new"})
        assert [m["voided_at"] for m in movements(conn, user.id)] == [None, None]


def test_substituir_uma_venda_nao_conta_as_duas_vendas_na_simulacao(user, as_user):
    """Posição 100, venda manual de 100 e a mesma venda na planilha: substituir não pode
    acusar venda descoberta (a manual sai na mesma transação)."""
    with as_user(user) as conn:
        manual_buy(conn, user.id)
        Ledger(conn).post(
            user.id,
            [
                MovementDraft(
                    idempotency_key=f"manual-{uuid4()}",
                    trade_date=date(2026, 1, 20),
                    type=MovementType.VENDA,
                    broker_id="corretora-teste-a",
                    ticker="TSTA3",
                    quantity=Decimal(100),
                    unit_price=Decimal(25),
                )
            ],
            origin=Origin.MANUAL,
        )
        sell_all = "20/01/2026;venda;TSTA3;acao;100;25,00;;;Corretora Teste A;;"
        preview = importers.preview(Ledger(conn), user.id, [csv(sell_all)])
        [row] = rows(preview)
        assert row.status == "possible_duplicate"
        result = importers.commit(Ledger(conn), user.id, preview.batch.id, {row.id: "replace"})
        assert result.replaced == 1


def test_carteira_mudou_entre_a_previa_e_a_gravacao(user, as_user):
    with as_user(user) as conn:
        manual_buy(conn, user.id)
        preview = importers.preview(Ledger(conn), user.id, [csv(SELL)])
        assert statuses(preview) == ["ok"]
        manual_id = conn.execute(
            "select id from ledger.movements where user_id = %s", [user.id]
        ).fetchone()["id"]
    with as_user(user) as conn:
        Ledger(conn).void(user.id, manual_id, "teste")
    with as_user(user) as conn, pytest.raises(importers.CommitRejectedError) as exc:
        importers.commit(Ledger(conn), user.id, preview.batch.id, {})
    assert "Linha 2" in exc.value.messages[0]
    assert "Venda maior que a posição" in exc.value.messages[0]


def test_decisoes_invalidas_sao_recusadas(user, as_user):
    with as_user(user) as conn:
        preview = importers.preview(Ledger(conn), user.id, [csv(BUY)])
        [row] = rows(preview)
        with pytest.raises(importers.ImportRejectedError, match="Decisão inválida"):
            importers.commit(Ledger(conn), user.id, preview.batch.id, {row.id: "replace"})
        with pytest.raises(importers.ImportRejectedError, match="não é deste lote"):
            importers.commit(Ledger(conn), user.id, preview.batch.id, {uuid4(): "import"})


def test_descartar_fecha_o_lote(user, as_user):
    with as_user(user) as conn:
        preview = importers.preview(Ledger(conn), user.id, [csv(BUY)])
        importers.discard(Ledger(conn), user.id, preview.batch.id)
        with pytest.raises(importers.BatchClosedError):
            importers.commit(Ledger(conn), user.id, preview.batch.id, {})
        assert movements(conn, user.id) == []


def test_lote_de_outro_usuario_e_invisivel(user, make_user, as_user):
    other = make_user()
    with as_user(user) as conn:
        preview = importers.preview(Ledger(conn), user.id, [csv(BUY)])
    with as_user(other) as conn:
        assert Ledger(conn).imports.batch(other.id, preview.batch.id) is None
        assert conn.execute("select count(*) as n from imports.rows").fetchone()["n"] == 0
        with pytest.raises(importers.BatchNotFoundError):
            importers.commit(Ledger(conn), other.id, preview.batch.id, {})


def test_arquivo_repetido_e_ilegivel_no_mesmo_envio(user, as_user):
    good = csv(BUY)
    with as_user(user) as conn:
        preview = importers.preview(
            Ledger(conn), user.id, [good, good, Upload("notas.pdf", b"%PDF-1.7")]
        )
        assert [p.index for p in preview.problems] == [1, 2]
        assert "repetido" in preview.problems[0].message
        assert preview.file_indexes == (0,)


def test_mesma_linha_em_dois_arquivos_do_mesmo_envio_entra_uma_vez(user, as_user):
    with as_user(user) as conn:
        preview = importers.preview(
            Ledger(conn), user.id, [csv(BUY, INCOME), csv(INCOME, SELL, "")]
        )
        assert statuses(preview) == ["ok", "ok", "ignored", "ok"]
        result = importers.commit(Ledger(conn), user.id, preview.batch.id, {})
        assert result.created == 3


def test_nada_com_cara_de_cpf_chega_ao_banco(user, as_user):
    line = "05/01/2026;compra;TSTA3;acao;1;20,00;;;Corretora Teste A;;cpf 123.456.789-00"
    with as_user(user) as conn:
        preview = importers.preview(Ledger(conn), user.id, [csv(line)])
        stored = conn.execute(
            "select raw::text || coalesce(draft::text, '') as t from imports.rows r"
            " join imports.files f on f.id = r.file_id where f.batch_id = %s",
            [preview.batch.id],
        ).fetchone()["t"]
        assert "123.456.789-00" not in stored
        assert "***" in stored


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tesouro_2099(admin_url):
    """Título fictício (vencimento em 2099) para não colidir com o cadastro real."""
    with admin_connection(admin_url) as conn:
        conn.execute(
            "insert into market.assets (ticker, class, name, maturity_date)"
            " values ('TD-SELIC-01032099', 'tesouro', 'Tesouro Selic 2099 (01/03/2099)',"
            " date '2099-03-01') on conflict (ticker) do nothing"
        )
    return "TD-SELIC-01032099"


def b3_files():
    return [
        Upload(name, (FIXTURES / name).read_bytes())
        for name in ("b3-negociacao.xlsx", "b3-movimentacao.xlsx")
    ]


def test_b3_negociacao_e_movimentacao_juntas(user, as_user, tesouro_2099):
    with as_user(user) as conn:
        preview = importers.preview(Ledger(conn), user.id, b3_files())
        negociacao, movimentacao = preview.batch.files
        assert negociacao.adapter == "b3-negociacao"
        assert [r.status for r in negociacao.rows] == ["ok"] * 5 + ["ignored", "ok", "ok"]
        assert any("corretagem" in w for w in preview.batch.warnings)

        by_line = {r.line_numbers[0]: r for r in movimentacao.rows}
        assert by_line[5].status == "ignored"  # liquidação: reflexo da negociação
        desdobro = by_line[9]
        assert desdobro.line_numbers == (9, 10)
        assert desdobro.status == "ok"
        assert desdobro.draft["factor"] == "2"
        assert "posição de 127" in desdobro.messages[0]["text"]
        bonus = by_line[12]
        assert bonus.draft["factor"] == "0.1"
        assert bonus.draft["unit_price"] == "95"
        assert by_line[11].draft["ticker"] == tesouro_2099
        assert by_line[14].status == "error"  # Atualização: lançar à mão

        result = importers.commit(Ledger(conn), user.id, preview.batch.id, {})
        assert result.created == 7 + 6
        labels = conn.execute(
            "select distinct origin_label from ledger.movements where user_id = %s", [user.id]
        ).fetchall()
        assert [r["origin_label"] for r in labels] == ["B3"]

    # Reenviar os dois arquivos não muda nada (inclusive o evento agrupado).
    with as_user(user) as conn:
        again = importers.preview(Ledger(conn), user.id, b3_files())
        statuses_again = {r.status for f in again.batch.files for r in f.rows}
        assert "ok" not in statuses_again


def test_b3_compra_manual_igual_a_negociacao_vira_duplicado(user, as_user, tesouro_2099):
    with as_user(user) as conn:
        manual_buy(conn, user.id, quantity="100", day=date(2026, 1, 5))
        preview = importers.preview(Ledger(conn), user.id, b3_files()[:1])
        first = preview.batch.files[0].rows[0]
        assert first.status == "possible_duplicate"
        assert "Manual" in first.messages[0]["text"]
