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
        assert again.json() == {"created": [], "already_posted": first.json()["created"]}

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
