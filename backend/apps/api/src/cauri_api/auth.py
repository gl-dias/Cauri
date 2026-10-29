"""Verificação do JWT emitido pelo Supabase Auth.

Projetos novos do Supabase assinam com chave assimétrica (ES256/RS256) publicada no
JWKS; o Supabase local e projetos antigos usam HS256 com segredo. Os dois caminhos
são aceitos, cada um só se estiver configurado.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from jwt.types import Options

from cauri_api.settings import Settings

_ASYMMETRIC = {"ES256", "RS256"}


class AuthError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: UUID
    email: str
    claims: dict[str, Any]


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret
        self._audience = settings.jwt_audience
        self._jwks: jwt.PyJWKClient | None = None
        if settings.supabase_url:
            url = settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
            self._jwks = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)

    def verify(self, token: str) -> AuthUser:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError("token malformado") from exc
        algorithm = header.get("alg")
        options: Options = {"require": ["exp", "sub", "aud"]}
        try:
            if algorithm == "HS256" and self._secret:
                claims = jwt.decode(
                    token,
                    self._secret,
                    algorithms=["HS256"],
                    audience=self._audience,
                    options=options,
                )
            elif algorithm in _ASYMMETRIC and self._jwks is not None:
                key = self._jwks.get_signing_key_from_jwt(token).key
                claims = jwt.decode(
                    token, key, algorithms=[algorithm], audience=self._audience, options=options
                )
            else:
                raise AuthError(f"algoritmo de assinatura não aceito: {algorithm}")
        except jwt.PyJWTError as exc:
            raise AuthError("token inválido ou expirado") from exc

        if claims.get("role") != "authenticated":
            raise AuthError("token não é de usuário autenticado")
        email = claims.get("email")
        if not isinstance(email, str) or not email:
            raise AuthError("token sem e-mail")
        try:
            user_id = UUID(str(claims["sub"]))
        except ValueError as exc:
            raise AuthError("sub inválido") from exc
        return AuthUser(id=user_id, email=email.lower(), claims=claims)
