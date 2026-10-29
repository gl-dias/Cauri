"""API de ponta a ponta contra o Supabase local, com JWT assinado como o Supabase local assina."""

import time
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from cauri_api.main import create_app
from cauri_api.settings import Settings

pytestmark = pytest.mark.db

# Segredo público do Supabase local (o mesmo para toda instalação da CLI).
LOCAL_JWT_SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


def token_for(user, *, secret=LOCAL_JWT_SECRET, expires_in=3600, **overrides):
    claims = {
        "sub": str(user.id),
        "email": user.email,
        "role": "authenticated",
        "aud": "authenticated",
        "exp": int(time.time()) + expires_in,
        **overrides,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest.fixture
def client(api_pool, api_url, reference_data):
    settings = Settings(database_url=api_url, jwt_secret=LOCAL_JWT_SECRET, supabase_url=None)
    with TestClient(create_app(settings, pool=api_pool)) as c:
        yield c


def auth(user, **kw):
    return {"Authorization": f"Bearer {token_for(user, **kw)}"}


def entry(**overrides):
    base = {
        "client_key": str(uuid4()),
        "type": "compra",
        "trade_date": "2026-03-02",
        "broker_id": "corretora-teste-a",
        "ticker": "tsta3",
        "quantity": "10",
        "unit_price": "20,50",
        "fees": "1,00",
    }
    base.update(overrides)
    return base


class TestAutenticacao:
    def test_sem_token_e_401(self, client):
        assert client.get("/v1/me").status_code == 401

    def test_token_com_assinatura_errada_e_401(self, client, make_user):
        user = make_user()
        # Segredo falso de propósito, para o token sair com assinatura inválida.
        wrong = "outro-segredo-qualquer-com-mais-de-32-caracteres"  # gitleaks:allow
        headers = auth(user, secret=wrong)
        assert client.get("/v1/me", headers=headers).status_code == 401

    def test_token_expirado_e_401(self, client, make_user):
        assert client.get("/v1/me", headers=auth(make_user(), expires_in=-10)).status_code == 401

    def test_token_anon_nao_serve(self, client, make_user):
        assert client.get("/v1/me", headers=auth(make_user(), role="anon")).status_code == 401

    def test_quem_nao_esta_na_allowlist_e_barrado(self, client, make_user):
        outsider = make_user(member=False)
        response = client.get("/v1/me", headers=auth(outsider))
        assert response.status_code == 403
        assert response.json()["detail"] == "Acesso restrito a convidados."

    def test_me_devolve_papel(self, client, make_user):
        admin = make_user(role="admin")
        body = client.get("/v1/me", headers=auth(admin)).json()
        assert body["role"] == "admin"
        assert body["email"] == admin.email


class TestLancamentoManual:
    def test_conferir_depois_gravar_e_reenviar_nao_duplica(self, client, make_user):
        user = make_user()
        payload = {"entries": [entry()]}
        check = client.post("/v1/movements/check", json=payload, headers=auth(user))
        assert check.status_code == 200
        assert check.json()["ok"] is True

        first = client.post("/v1/movements", json=payload, headers=auth(user))
        assert first.status_code == 201
        assert len(first.json()["created"]) == 1

        again = client.post("/v1/movements", json=payload, headers=auth(user))
        assert again.json()["created"] == []
        assert again.json()["already_posted"] == first.json()["created"]

    def test_gravar_ja_recalcula_os_snapshots(self, client, make_user, api_pool):
        user = make_user()
        response = client.post("/v1/movements", json={"entries": [entry()]}, headers=auth(user))
        assert response.json()["snapshots_updated"] is True
        from cauri_storage import user_transaction

        with user_transaction(api_pool, user.claims) as conn:
            snap = conn.execute(
                "select min(snap_date) as first, count(*) as n from engine.portfolio_snapshots"
                " where user_id = %s",
                [user.id],
            ).fetchone()
            dirty = conn.execute(
                "select count(*) as n from engine.dirty_ranges where user_id = %s", [user.id]
            ).fetchone()
        assert snap["first"].isoformat() == "2026-03-02"
        assert snap["n"] > 100  # um snapshot por pregão até o último fechamento
        assert dirty["n"] == 0

    def test_venda_descoberta_volta_422_com_o_motivo(self, client, make_user):
        user = make_user()
        client.post("/v1/movements", json={"entries": [entry(quantity="5")]}, headers=auth(user))
        response = client.post(
            "/v1/movements",
            json={"entries": [entry(type="venda", quantity="6", trade_date="2026-03-03")]},
            headers=auth(user),
        )
        assert response.status_code == 422
        error = response.json()["checks"][0]["errors"][0]
        assert error["code"] == "oversell"
        assert "TSTA3" in error["message"]

    def test_numero_como_json_number_e_recusado(self, client, make_user):
        response = client.post(
            "/v1/movements/check",
            json={"entries": [entry(quantity=10.5)]},
            headers=auth(make_user()),
        )
        assert response.status_code == 422

    def test_numero_ilegivel_aponta_o_campo(self, client, make_user):
        response = client.post(
            "/v1/movements/check",
            json={"entries": [entry(unit_price="vinte")]},
            headers=auth(make_user()),
        )
        assert response.status_code == 422
        assert response.json()["field"] == "unit_price"

    def test_editar_e_remover(self, client, make_user):
        user = make_user()
        created = client.post(
            "/v1/movements", json={"entries": [entry()]}, headers=auth(user)
        ).json()["created"][0]
        edit = client.patch(
            f"/v1/movements/{created}", json={"fees": "2,00", "reason": "nota"}, headers=auth(user)
        )
        assert edit.status_code == 204
        void = client.post(
            f"/v1/movements/{created}/void", json={"reason": "duplicada"}, headers=auth(user)
        )
        assert void.status_code == 204
        again = client.patch(f"/v1/movements/{created}", json={"fees": "3,00"}, headers=auth(user))
        assert again.status_code == 409

    def test_usuario_nao_edita_nem_remove_movimentacao_de_outro(self, client, make_user):
        ana, bruno = make_user(), make_user()
        created = client.post(
            "/v1/movements", json={"entries": [entry()]}, headers=auth(ana)
        ).json()["created"][0]
        assert (
            client.patch(
                f"/v1/movements/{created}", json={"fees": "9"}, headers=auth(bruno)
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/v1/movements/{created}/void", json={"reason": "x"}, headers=auth(bruno)
            ).status_code
            == 404
        )

    def test_remocao_exige_motivo(self, client, make_user):
        user = make_user()
        created = client.post(
            "/v1/movements", json={"entries": [entry()]}, headers=auth(user)
        ).json()["created"][0]
        assert (
            client.post(
                f"/v1/movements/{created}/void", json={"reason": ""}, headers=auth(user)
            ).status_code
            == 422
        )


class TestAdmin:
    def test_usuario_comum_nao_ve_a_allowlist(self, client, make_user):
        assert client.get("/v1/admin/allowlist", headers=auth(make_user())).status_code == 403

    def test_admin_adiciona_e_remove_email(self, client, make_user):
        admin = make_user(role="admin")
        email = f"Convidado-{uuid4().hex[:8]}@Example.test"
        added = client.post("/v1/admin/allowlist", json={"email": email}, headers=auth(admin))
        assert added.status_code == 201
        assert added.json()["email"] == email.lower()
        assert (
            client.post(
                "/v1/admin/allowlist", json={"email": email}, headers=auth(admin)
            ).status_code
            == 409
        )
        assert client.delete(f"/v1/admin/allowlist/{email}", headers=auth(admin)).status_code == 204
        assert client.delete(f"/v1/admin/allowlist/{email}", headers=auth(admin)).status_code == 404

    def test_removido_da_allowlist_perde_acesso_na_hora(self, client, make_user):
        admin, user = make_user(role="admin"), make_user()
        assert client.get("/v1/me", headers=auth(user)).status_code == 200
        client.delete(f"/v1/admin/allowlist/{user.email}", headers=auth(admin))
        assert client.get("/v1/me", headers=auth(user)).status_code == 403

    def test_email_invalido_e_recusado(self, client, make_user):
        admin = make_user(role="admin")
        assert (
            client.post(
                "/v1/admin/allowlist", json={"email": "sem-arroba"}, headers=auth(admin)
            ).status_code
            == 422
        )


IMPORT_CSV = (
    b"data;tipo;ativo;classe;quantidade;preco;valor;corretora\n"
    b"05/01/2026;compra;TSTA3;acao;10;20,00;;Corretora Teste A\n"
    b"15/01/2026;provento;TSTF11;fii;;;3,21;corretora-teste-b\n"
    b"16/01/2026;compra;NAOEXISTE3;acao;1;1,00;;Corretora Teste A\n"
)


def upload(client, user, *files):
    return client.post(
        "/v1/imports",
        files=[("files", (name, content, "text/csv")) for name, content in files],
        headers=auth(user),
    )


class TestImportacao:
    def test_previa_depois_gravacao_e_historico(self, client, make_user):
        user = make_user()
        res = upload(client, user, ("minha planilha.csv", IMPORT_CSV))
        assert res.status_code == 201
        body = res.json()
        batch = body["batch"]
        assert body["problems"] == []
        assert batch["status"] == "preview"
        assert batch["counts"] == {"ok": 2, "error": 1}
        ok, income, bad = batch["files"][0]["rows"]
        assert ok["draft"]["broker_name"] == "Corretora Teste A"
        assert ok["draft"]["quantity"] == "10"
        assert income["draft"]["income_kind"] == "rendimento"
        assert bad["status"] == "error"
        assert "NAOEXISTE3" in bad["messages"][0]["text"]
        # O nome do arquivo não é guardado: o lote tem um rótulo gerado.
        assert batch["files"][0]["label"].startswith("Template do Cauri")

        res = client.post(f"/v1/imports/{batch['id']}/commit", json={}, headers=auth(user))
        assert res.status_code == 200
        assert res.json()["created"] == 2

        again = client.get(f"/v1/imports/{batch['id']}", headers=auth(user)).json()
        assert again["status"] == "committed"
        assert again["files"][0]["rows"][0]["movement_id"]
        history = client.get("/v1/imports", headers=auth(user)).json()
        assert history[0]["id"] == batch["id"]
        assert history[0]["imported"] == 2

        res = client.post(f"/v1/imports/{batch['id']}/commit", json={}, headers=auth(user))
        assert res.status_code == 409

    def test_lote_de_outro_usuario_e_404(self, client, make_user):
        ana, bruno = make_user(), make_user()
        batch = upload(client, ana, ("a.csv", IMPORT_CSV)).json()["batch"]
        assert client.get(f"/v1/imports/{batch['id']}", headers=auth(bruno)).status_code == 404
        res = client.post(f"/v1/imports/{batch['id']}/commit", json={}, headers=auth(bruno))
        assert res.status_code == 404

    def test_arquivo_ilegivel_volta_como_problema_sem_lote(self, client, make_user):
        res = upload(client, make_user(), ("extrato.pdf", b"%PDF-1.7"))
        assert res.status_code == 201
        assert res.json()["batch"] is None
        assert "Formato não suportado" in res.json()["problems"][0]["message"]

    def test_arquivo_grande_demais_e_recusado(self, client, make_user):
        big = b"data;tipo\n" + b"x" * (5 * 1024 * 1024 + 10)
        res = upload(client, make_user(), ("grande.csv", big))
        assert "5 MB" in res.json()["problems"][0]["message"]

    def test_decisao_desconhecida_e_422(self, client, make_user):
        user = make_user()
        batch = upload(client, user, ("a.csv", IMPORT_CSV)).json()["batch"]
        row_id = batch["files"][0]["rows"][0]["id"]
        res = client.post(
            f"/v1/imports/{batch['id']}/commit",
            json={"decisions": {row_id: "apagar"}},
            headers=auth(user),
        )
        assert res.status_code == 422

    def test_descartar(self, client, make_user):
        user = make_user()
        batch = upload(client, user, ("a.csv", IMPORT_CSV)).json()["batch"]
        assert (
            client.post(f"/v1/imports/{batch['id']}/discard", headers=auth(user)).status_code == 204
        )
        assert client.get("/v1/imports", headers=auth(user)).json() == []

    def test_sem_login_nao_importa(self, client):
        res = client.post("/v1/imports", files=[("files", ("a.csv", IMPORT_CSV, "text/csv"))])
        assert res.status_code == 401


UNKNOWN_CSV = ("Data Operação;Operação;Papel;Qtde;Preço\n05/01/2026;C;TSTA3;10;20,00\n").encode()
PROFILE = {
    "name": "Corretora Fictícia",
    "mapping": {
        "data": "Data Operação",
        "tipo": "Operação",
        "ativo": "Papel",
        "quantidade": "Qtde",
        "preco": "Preço",
    },
    "options": {"broker_id": "corretora-teste-a"},
}


class TestPerfisDeImportacao:
    def test_desconhecido_vira_perfil_e_depois_e_reconhecido(self, client, make_user):
        user = make_user()
        first = upload(client, user, ("corretora.csv", UNKNOWN_CSV)).json()
        assert first["batch"] is None
        assert first["problems"][0]["columns"] == [
            "Data Operação",
            "Operação",
            "Papel",
            "Qtde",
            "Preço",
        ]

        res = client.post("/v1/imports/profiles", json=PROFILE, headers=auth(user))
        assert res.status_code == 201
        profile = res.json()
        assert profile["options"]["decimal"] == ","

        second = upload(client, user, ("corretora.csv", UNKNOWN_CSV)).json()
        assert second["batch"]["files"][0]["adapter"].startswith("perfil-")
        assert second["batch"]["counts"] == {"ok": 1}

        listed = client.get("/v1/imports/profiles", headers=auth(user)).json()
        assert [p["name"] for p in listed] == ["Corretora Fictícia"]
        assert listed[0]["last_used_at"] is not None

        assert (
            client.delete(f"/v1/imports/profiles/{profile['id']}", headers=auth(user)).status_code
            == 204
        )
        assert client.get("/v1/imports/profiles", headers=auth(user)).json() == []

    def test_perfil_incompleto_e_recusado(self, client, make_user):
        user = make_user()
        no_broker = {**PROFILE, "options": {}}
        res = client.post("/v1/imports/profiles", json=no_broker, headers=auth(user))
        assert res.status_code == 422
        no_date = {**PROFILE, "mapping": {"tipo": "Operação", "ativo": "Papel"}}
        assert (
            client.post("/v1/imports/profiles", json=no_date, headers=auth(user)).status_code == 422
        )
        unknown_broker = {**PROFILE, "options": {"broker_id": "nao-existe"}}
        res = client.post("/v1/imports/profiles", json=unknown_broker, headers=auth(user))
        assert res.status_code == 422

    def test_perfil_de_outro_usuario_nao_e_apagado(self, client, make_user):
        ana, bruno = make_user(), make_user()
        profile = client.post("/v1/imports/profiles", json=PROFILE, headers=auth(ana)).json()
        res = client.delete(f"/v1/imports/profiles/{profile['id']}", headers=auth(bruno))
        assert res.status_code == 404
        assert len(client.get("/v1/imports/profiles", headers=auth(ana)).json()) == 1


class TestSaldoInicial:
    def test_lancamento_manual_de_saldo_inicial(self, client, make_user, as_user):
        user = make_user()
        body = {"entries": [entry(opening_balance=True, fees=None, unit_price="18,00")]}
        res = client.post("/v1/movements", json=body, headers=auth(user))
        assert res.status_code == 201
        with as_user(user) as conn:
            row = conn.execute(
                "select opening_balance, origin_label from ledger.movements where id = %s",
                [res.json()["created"][0]],
            ).fetchone()
        assert row["opening_balance"] is True
        assert row["origin_label"] == "Saldo inicial"

        sale = {"entries": [entry(type="venda", opening_balance=True)]}
        assert (
            client.post("/v1/movements/check", json=sale, headers=auth(user)).json()["ok"] is False
        )

    def test_venda_descoberta_na_importacao_sugere_e_aceita_saldo_inicial(self, client, make_user):
        user = make_user()
        sale = (
            b"data;tipo;ativo;classe;quantidade;preco;corretora\n"
            b"10/02/2026;venda;TSTA3;acao;30;25,00;Corretora Teste A\n"
        )
        batch = upload(client, user, ("venda.csv", sale)).json()["batch"]
        assert batch["counts"] == {"error": 1}
        [suggestion] = batch["suggestions"]
        assert suggestion["ticker"] == "TSTA3"
        assert suggestion["trade_date"] == "2026-02-09"
        assert suggestion["quantity"] == "30"

        res = client.post(
            f"/v1/imports/{batch['id']}/opening-balances",
            json={
                "ticker": "TSTA3",
                "trade_date": "2026-02-09",
                "quantity": "30",
                "unit_cost": "20,00",
                "broker_id": "corretora-teste-a",
            },
            headers=auth(user),
        )
        assert res.status_code == 200
        updated = res.json()
        assert updated["counts"] == {"ok": 2}
        assert updated["suggestions"] == []
        opening_file = updated["files"][-1]
        assert opening_file["label"] == "Saldos iniciais"
        assert opening_file["rows"][0]["draft"]["opening_balance"] is True
        res = client.post(f"/v1/imports/{batch['id']}/commit", json={}, headers=auth(user))
        assert res.json()["created"] == 2
