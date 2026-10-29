"""Configuração da API, só por variável de ambiente (prefixo ``CAURI_``)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAURI_", env_file=".env", extra="ignore")

    # Conexão como role cauri_api (nunca o dono do banco nem service role).
    database_url: str
    # URL do projeto Supabase: as chaves públicas do JWT vêm do JWKS dele.
    supabase_url: str | None = None
    # Segredo HS256: só para o Supabase local ou projetos com chave legada.
    jwt_secret: str | None = None
    jwt_audience: str = "authenticated"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )
    db_pool_max: int = 5
