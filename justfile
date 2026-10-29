# Atalhos de desenvolvimento do Cauri. Requer: just, uv, Docker (OrbStack no Mac) e a
# CLI do Supabase. No Mac: `brew install just uv supabase/tap/supabase`.
# No Windows, sem a CLI instalada, troque `supabase` por `npx supabase@2.122.0`.

set dotenv-load
set windows-shell := ["bash", "-cu"]

supabase := "supabase"
packages := "-p cauri_core -p cauri_storage -p cauri_engine -p cauri_ledger -p cauri_manual_entry -p cauri_importers -p cauri_nl_assistant -p cauri_ingest_market -p cauri_api -p cauri_jobs"

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

# Testes de interface com backend simulado (contraste AA, layout e screenshots)
e2e *args:
    cd web && npx playwright test {{args}}

# Haiku de verdade nas frases de exemplo (opcional, precisa de ANTHROPIC_API_KEY no ambiente)
test-llm:
    cd backend && CAURI_LLM_LIVE=1 uv run pytest packages/nl_assistant/tests/test_llm_live.py

# Ponta a ponta de verdade: precisa de `just db-start`, `just api` (com
# CAURI_ASSISTANT_EXTRACTOR=regras se não houver chave da Anthropic) e `npm run dev` no ar
e2e-live:
    cd web && CAURI_E2E_LIVE=1 npx playwright test e2e/app-live.spec.ts --project=desktop

# Workflows do GitHub Actions e segredos, antes de qualquer push (via Docker)
pre-push:
    docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.7 -no-color
    docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:v8.30.1 git /repo --config /repo/.gitleaks.toml --redact --exit-code 1

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

# Job diário de mercado e snapshots (ex.: just daily --pass second --date 2026-11-03)
daily *args:
    cd backend && uv run cauri-jobs daily {{args}}

# Recalcula snapshots de todas as carteiras (ou --user <id> --from AAAA-MM-DD)
recalc *args:
    cd backend && uv run cauri-jobs recalc {{args}}

# Histórico de preços e indicadores da união das carteiras (ex.: just backfill --since 2024-01-01)
backfill *args:
    cd backend && uv run cauri-jobs backfill {{args}}

# Tudo que o CI roda
check: lint test db-test
