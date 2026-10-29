"""Configuração dos jobs por variável de ambiente."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"defina a variável de ambiente {name}")
    return value


def _find_reference_dir() -> Path:
    configured = os.environ.get("CAURI_REFERENCE_DIR")
    if configured:
        return Path(configured)
    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        candidate = folder / "reference"
        if (candidate / "brokers.yaml").exists():
            return candidate
    raise ConfigError("pasta reference/ não encontrada (defina CAURI_REFERENCE_DIR)")


@dataclass(frozen=True)
class JobsConfig:
    @property
    def ingest_url(self) -> str:
        """Role cauri_ingest: escreve mercado, raw, ops e snapshots; não escreve no ledger."""
        return _require("CAURI_INGEST_DATABASE_URL")

    @property
    def admin_url(self) -> str:
        """Dono do banco. Só seed do demo e bootstrap do admin; nunca no job diário."""
        return _require("CAURI_ADMIN_DATABASE_URL")

    @property
    def admin_email(self) -> str:
        return _require("CAURI_ADMIN_EMAIL").lower()

    @property
    def cache_dir(self) -> Path:
        return Path(os.environ.get("CAURI_CACHE_DIR", ".cache/market"))

    @property
    def reference_dir(self) -> Path:
        return _find_reference_dir()

    @property
    def brapi_token(self) -> str | None:
        return os.environ.get("BRAPI_API_KEY") or None

    @property
    def brapi_monthly_quota(self) -> int:
        return int(os.environ.get("CAURI_BRAPI_MONTHLY_QUOTA", "15000"))

    @property
    def coingecko_key(self) -> str | None:
        return os.environ.get("COINGECKO_API_KEY") or None

    @property
    def git_sha(self) -> str | None:
        return os.environ.get("GITHUB_SHA") or os.environ.get("CAURI_GIT_SHA") or None

    @property
    def trigger(self) -> str:
        return "cron" if os.environ.get("GITHUB_EVENT_NAME") == "schedule" else "manual"
