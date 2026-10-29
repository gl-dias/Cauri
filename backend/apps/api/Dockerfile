# syntax=docker/dockerfile:1.7
#
# Imagem da API do Cauri. Portável: roda igual na VPS (Docker Compose) e no Cloud Run.
# Toda configuração vem do ambiente (CAURI_*); nenhum segredo entra na imagem.
#
# Build (contexto = backend/):
#   docker build -f apps/api/Dockerfile -t cauri-api .

# Etapa 1: resolve e instala só o pacote cauri-api e as dependências dele do workspace.
FROM ghcr.io/astral-sh/uv:0.13.6-python3.13-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app
COPY . .

# --no-editable: o código vai para dentro do .venv, e a etapa final não precisa dos fontes.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package cauri-api

# Etapa 2: runtime enxuto, mesmo Python da etapa 1, usuário sem privilégio.
FROM python:3.13-slim-trixie AS runtime

RUN groupadd --system --gid 10001 cauri \
    && useradd --system --uid 10001 --gid cauri --no-create-home --shell /usr/sbin/nologin cauri

WORKDIR /app
COPY --from=builder --chown=cauri:cauri /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

USER cauri
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=4)"]

# PORT vem do ambiente (Cloud Run define sozinho; na VPS fica o padrão 8000).
# --proxy-headers: atrás do Nginx (ou do front do Cloud Run), o IP real vem do X-Forwarded-For.
CMD ["sh", "-c", "exec uvicorn --factory cauri_api.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --proxy-headers --forwarded-allow-ips='*'"]
