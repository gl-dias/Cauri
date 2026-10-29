# Atalhos de desenvolvimento do Cauri. Requer: just, uv, Docker (OrbStack no Mac) e a
# CLI do Supabase. No Mac: `brew install just uv supabase/tap/supabase`.
# No Windows, sem a CLI instalada, troque `supabase` por `npx supabase@2.122.0`.

set dotenv-load
set windows-shell := ["bash", "-cu"]

supabase := "supabase"
packages := "-p cauri_core -p cauri_storage -p cauri_engine -p cauri_ledger -p cauri_manual_entry -p cauri_ingest_market -p cauri_api -p cauri_jobs"

# Lista os recipes
default:
    @just --list

# Sobe o Supabase local (Postgres, Auth, PostgREST, Studio)
db-start:
    {{supabase}} start

# Recria o banco local aplicando todas as migrations e o seed.sql
db-reset:
    {{supabase}} db reset

# Testes de banco em pgTAP (RLS, isolamento, invariantes do ledger)
db-test:
    {{supabase}} test db

# Instala o workspace Python (todos os pacotes + dev)
sync:
    cd backend && uv sync --all-packages

# Lint, formatação, tipos e fronteiras entre módulos
lint:
    cd backend && uv run ruff check .
    cd backend && uv run ruff format --check .
    cd backend && uv run mypy {{packages}}
    cd backend && uv run lint-imports

# Testes Python (os marcados com `db` precisam do Supabase local no ar)
test *args:
    cd backend && uv run pytest {{args}}

# API local com reload, apontando para o banco local (variáveis do .env)
api:
    cd backend && uv run uvicorn --factory cauri_api.main:app --reload --host 127.0.0.1 --port 8000

# Dados de referência, ativos da B3 e do Tesouro, carteira demo (já busca o histórico de
# preços reais dos ativos dela) e admin inicial (CAURI_ADMIN_EMAIL)
seed:
    cd backend && uv run cauri-jobs sync-reference
    cd backend && uv run cauri-jobs sync-assets
    cd backend && uv run cauri-jobs seed-demo
    cd backend && uv run cauri-jobs bootstrap-admin

# Histórico de preços e indicadores da união das carteiras (ex.: just backfill --since 2024-01-01)
backfill *args:
    cd backend && uv run cauri-jobs backfill {{args}}

# Tudo que o CI roda
check: lint test db-test
