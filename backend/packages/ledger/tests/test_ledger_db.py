"""Ledger contra o Postgres local, com o RLS do usuário (role authenticated)."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from cauri_core import FiKind, MovementType, Origin
from cauri_ledger import (
    FixedIncomeDraft,
    IssueCode,
    Ledger,
    LedgerValidationError,
    MovementChangeRejectedError,
    MovementDraft,
    MovementNotFoundError,
    MovementPatch,
)

pytestmark = pytest.mark.db

BROKER = "corretora-teste-a"


def trade(kind, qty, price, day, ticker="TSTA3", **extra):
    return MovementDraft(
        idempotency_key=extra.pop("key", f"teste-{uuid4()}"),
        trade_date=day,
        type=kind,
        broker_id=extra.pop("broker", BROKER),
        ticker=ticker,
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        **extra,
    )


def cdb_draft(kind, amount, day, **extra):
    return MovementDraft(
        idempotency_key=f"teste-{uuid4()}",
        trade_date=day,
        type=kind,
        broker_id=BROKER,
        fixed_income=FixedIncomeDraft(FiKind.CDB, "Banco Teste", Decimal(110), date(2028, 1, 3)),
        amount=Decimal(amount),
        **extra,
    )


@pytest.fixture
def user(make_user, reference_data):
    return make_user()


def test_venda_maior_que_a_posicao_e_recusada_com_mensagem(user, as_user):
    with as_user(user) as conn:
        Ledger(conn).post(
            user.id, [trade(MovementType.COMPRA, 10, 20, date(2026, 1, 5))], origin=Origin.MANUAL
        )
    with as_user(user) as conn:
        checks = Ledger(conn).check(
            user.id, [trade(MovementType.VENDA, 11, 25, date(2026, 1, 6))], origin=Origin.MANUAL
        )
        assert not checks[0].ok
        issue = checks[0].errors[0]
        assert issue.code is IssueCode.OVERSELL
        assert "TSTA3" in issue.message
        assert "06/01/2026" in issue.message
        assert "10" in issue.message
        with pytest.raises(LedgerValidationError):
            Ledger(conn).post(
                user.id, [trade(MovementType.VENDA, 11, 25, date(2026, 1, 6))], origin=Origin.MANUAL
            )


def test_compra_e_venda_no_mesmo_envio_se_cobrem(user, as_user):
    with as_user(user) as conn:
        result = Ledger(conn).post(
            user.id,
            [
                trade(MovementType.VENDA, 5, 22, date(2026, 2, 3)),
                trade(MovementType.COMPRA, 5, 20, date(2026, 2, 2)),
            ],
            origin=Origin.MANUAL,
        )
    assert len(result.created) == 2


def test_reenviar_o_mesmo_rascunho_nao_duplica(user, as_user):
    draft = trade(MovementType.COMPRA, 10, 20, date(2026, 1, 5), key="mesma-chave-sempre")
    with as_user(user) as conn:
        first = Ledger(conn).post(user.id, [draft], origin=Origin.MANUAL)
    with as_user(user) as conn:
        second = Ledger(conn).post(user.id, [draft], origin=Origin.MANUAL)
        count = conn.execute(
            "select count(*) as n from ledger.movements where user_id = %s", [user.id]
        ).fetchone()
    assert second.created == ()
    assert second.already_posted == first.created
    assert count is not None
    assert count["n"] == 1


def test_mesma_operacao_vinda_de_outra_origem_aparece_como_duplicado(user, as_user):
    with as_user(user) as conn:
        Ledger(conn).post(
            user.id,
            [trade(MovementType.COMPRA, 7, 30, date(2026, 3, 2), ticker="TSTB4")],
            origin=Origin.CHAT,
        )
    with as_user(user) as conn:
        from_sheet = trade(MovementType.COMPRA, 7, "30.10", date(2026, 3, 2), ticker="TSTB4")
        checks = Ledger(conn).check(user.id, [from_sheet], origin=Origin.IMPORT)
        other_qty = Ledger(conn).check(
            user.id,
            [trade(MovementType.COMPRA, 8, 30, date(2026, 3, 2), ticker="TSTB4")],
            origin=Origin.IMPORT,
        )
    assert checks[0].ok
    assert len(checks[0].duplicates) == 1
    assert checks[0].duplicates[0].origin is Origin.CHAT
    assert other_qty[0].duplicates == ()


def test_edicao_guarda_versao_motivo_e_valor_anterior(user, as_user):
    with as_user(user) as conn:
        created = Ledger(conn).post(
            user.id,
            [trade(MovementType.COMPRA, 10, 20, date(2026, 1, 5), fees=Decimal("4.90"))],
            origin=Origin.MANUAL,
        )
    movement_id = created.created[0]
    with as_user(user) as conn:
        Ledger(conn).amend(
            user.id, movement_id, MovementPatch(fees=Decimal("5.10")), reason="taxa da nota"
        )
    with as_user(user) as conn:
        row = conn.execute(
            "select version, fees from ledger.movements where id = %s", [movement_id]
        ).fetchone()
        history = conn.execute(
            "select op, reason, before ->> 'fees' as before_fees from ledger.movement_history"
            " where movement_id = %s order by version",
            [movement_id],
        ).fetchall()
    assert row == {"version": 2, "fees": Decimal("5.10")}
    assert [h["op"] for h in history] == ["insert", "update"]
    assert history[1]["reason"] == "taxa da nota"
    assert Decimal(history[1]["before_fees"]) == Decimal("4.90")


def test_edicao_que_descobre_venda_posterior_e_recusada(user, as_user):
    with as_user(user) as conn:
        created = Ledger(conn).post(
            user.id,
            [
                trade(MovementType.COMPRA, 10, 20, date(2026, 1, 5)),
                trade(MovementType.VENDA, 8, 22, date(2026, 1, 9)),
            ],
            origin=Origin.MANUAL,
        )
    buy_id = created.created[0]
    with as_user(user) as conn, pytest.raises(MovementChangeRejectedError, match="descoberta"):
        Ledger(conn).amend(user.id, buy_id, MovementPatch(quantity=Decimal(5)), reason=None)
    with as_user(user) as conn, pytest.raises(MovementChangeRejectedError, match="descoberta"):
        Ledger(conn).amend(
            user.id, buy_id, MovementPatch(trade_date=date(2026, 1, 12)), reason=None
        )


def test_remocao_e_soft_delete_e_respeita_a_linha_do_tempo(user, as_user):
    with as_user(user) as conn:
        created = Ledger(conn).post(
            user.id,
            [
                trade(MovementType.COMPRA, 10, 20, date(2026, 1, 5)),
                trade(MovementType.VENDA, 8, 22, date(2026, 1, 9)),
            ],
            origin=Origin.MANUAL,
        )
    buy_id, sell_id = created.created
    with as_user(user) as conn, pytest.raises(MovementChangeRejectedError):
        Ledger(conn).void(user.id, buy_id, reason="lançada errado")
    with as_user(user) as conn:
        Ledger(conn).void(user.id, sell_id, reason="venda duplicada")
        Ledger(conn).void(user.id, sell_id, reason="de novo")  # idempotente
    with as_user(user) as conn:
        row = conn.execute(
            "select voided_at is not null as voided, void_reason"
            " from ledger.movements where id = %s",
            [sell_id],
        ).fetchone()
        Ledger(conn).void(user.id, buy_id, reason="agora pode")
    assert row == {"voided": True, "void_reason": "venda duplicada"}


def test_usuario_nao_mexe_na_movimentacao_de_outro(make_user, reference_data, as_user):
    ana, bruno = make_user(), make_user()
    with as_user(ana) as conn:
        created = Ledger(conn).post(
            ana.id, [trade(MovementType.COMPRA, 1, 10, date(2026, 1, 5))], origin=Origin.MANUAL
        )
    movement_id = created.created[0]
    with as_user(bruno) as conn:
        with pytest.raises(MovementNotFoundError):
            Ledger(conn).amend(bruno.id, movement_id, MovementPatch(notes="invasão"), reason=None)
        with pytest.raises(MovementNotFoundError):
            Ledger(conn).void(bruno.id, movement_id, reason="invasão")
        # Mesmo passando o id da ana como dono, o RLS não deixa gravar por ela.
        with pytest.raises(Exception, match="row-level security"):
            Ledger(conn).post(
                ana.id, [trade(MovementType.COMPRA, 1, 10, date(2026, 1, 5))], origin=Origin.MANUAL
            )


def test_grupamento_que_descobre_venda_posterior_e_apontado(user, as_user):
    with as_user(user) as conn:
        Ledger(conn).post(
            user.id,
            [
                trade(MovementType.COMPRA, 100, 1, date(2026, 1, 5)),
                trade(MovementType.VENDA, 50, 1, date(2026, 3, 2)),
            ],
            origin=Origin.MANUAL,
        )
    grupamento = MovementDraft(
        idempotency_key=f"teste-{uuid4()}",
        trade_date=date(2026, 2, 2),
        type=MovementType.GRUPAMENTO,
        broker_id=BROKER,
        ticker="TSTA3",
        factor=Decimal("0.1"),
    )
    with as_user(user) as conn:
        checks = Ledger(conn).check(user.id, [grupamento], origin=Origin.MANUAL)
    assert checks[0].errors[0].code is IssueCode.OVERSELL
    assert "deixa descoberta" in checks[0].errors[0].message


def test_renda_fixa_reaproveita_o_titulo_e_barra_resgate_acima_do_saldo(user, as_user):
    with as_user(user) as conn:
        Ledger(conn).post(
            user.id,
            [cdb_draft(MovementType.APORTE, "1000.00", date(2026, 3, 2))],
            origin=Origin.MANUAL,
        )
        Ledger(conn).post(
            user.id,
            [cdb_draft(MovementType.APORTE, "500.00", date(2026, 4, 1))],
            origin=Origin.MANUAL,
        )
    with as_user(user) as conn:
        instruments = conn.execute(
            "select count(*) as n from ledger.fi_instruments where user_id = %s", [user.id]
        ).fetchone()
        checks = Ledger(conn).check(
            user.id,
            [cdb_draft(MovementType.RESGATE, "2000.00", date(2026, 5, 4))],
            origin=Origin.MANUAL,
        )
        ok = Ledger(conn).check(
            user.id,
            [cdb_draft(MovementType.RESGATE, "1200.00", date(2026, 5, 4))],
            origin=Origin.MANUAL,
        )
    assert instruments is not None
    assert instruments["n"] == 1
    assert checks[0].errors[0].code is IssueCode.REDEMPTION_EXCEEDS_BALANCE
    assert ok[0].ok


def test_ativo_e_corretora_desconhecidos(user, as_user):
    with as_user(user) as conn:
        checks = Ledger(conn).check(
            user.id,
            [
                trade(
                    MovementType.COMPRA, 1, 1, date(2026, 1, 5), ticker="XXXX9", broker="nao-existe"
                )
            ],
            origin=Origin.MANUAL,
        )
    assert {i.code for i in checks[0].errors} == {IssueCode.UNKNOWN_ASSET, IssueCode.UNKNOWN_BROKER}
