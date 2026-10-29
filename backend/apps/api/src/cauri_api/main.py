"""API de escrita do Cauri. Leitura dos dashboards vai direto no Supabase (views marts)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cauri_api import errors, routes
from cauri_api.auth import TokenVerifier
from cauri_api.settings import Settings
from cauri_storage import Pool, make_pool


def create_app(settings: Settings | None = None, *, pool: Pool | None = None) -> FastAPI:
    settings = settings or Settings()  # vem do ambiente

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        own_pool = pool is None
        app.state.pool = pool or make_pool(settings.database_url, max_size=settings.db_pool_max)
        app.state.verifier = TokenVerifier(settings)
        yield
        if own_pool:
            app.state.pool.close()

    app = FastAPI(title="Cauri API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    errors.install(app)
    app.include_router(routes.movements.router)
    app.include_router(routes.imports.router)
    app.include_router(routes.account.router)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def app() -> FastAPI:
    """Fábrica para o uvicorn: ``uvicorn --factory cauri_api.main:app``."""
    return create_app()
