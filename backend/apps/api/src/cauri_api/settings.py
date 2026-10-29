"""Configuração da API, só por variável de ambiente (prefixo ``CAURI_``; as chaves dos
provedores usam o nome padrão de cada um, como no ``.env.example``)."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field
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
    # Assistente: Haiku com saída estruturada. "regras" é só para desenvolvimento e testes
    # sem chave (entende frases simples). Sem chave e sem "regras", o assistente fica fora.
    anthropic_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CAURI_ANTHROPIC_API_KEY")
    )
    anthropic_model: str = "claude-haiku-5-5"
    assistant_extractor: Literal["anthropic", "regras"] = "anthropic"
    # Transcrição de voz (Whisper pela Groq). Sem chave, o front usa a do navegador.
    groq_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("GROQ_API_KEY", "CAURI_GROQ_API_KEY")
    )
