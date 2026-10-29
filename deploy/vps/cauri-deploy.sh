#!/usr/bin/env bash
# Único comando que a chave de deploy do GitHub pode rodar na VPS. Fica em
# /usr/local/bin/cauri-deploy (dono root, ninguém mais escreve) e é forçado no
# authorized_keys do usuário cauri-deploy:
#
#   restrict,command="/usr/local/bin/cauri-deploy" ssh-ed25519 AAAA... cauri-deploy@github-actions
#
# O workflow chama `ssh cauri-deploy@vps deploy <sha> <usuario>` e manda o token do job
# pelo stdin. Qualquer outra coisa (shell, outro comando, sha inválido) é recusada.
#
# Em /opt/cauri:
#   .env      só GHCR_OWNER e CAURI_API_TAG (sem segredo; este script reescreve a tag)
#   api.env   segredos da API (root:cauri-deploy, 640)
set -euo pipefail

dir="${CAURI_DIR:-/opt/cauri}"
read -r action tag actor extra <<<"${SSH_ORIGINAL_COMMAND:-}" || true

if [[ "${action:-}" != deploy || ! "${tag:-}" =~ ^[0-9a-f]{40}$ \
  || ! "${actor:-}" =~ ^[A-Za-z0-9][A-Za-z0-9-]{0,38}(\[bot\])?$ || -n "${extra:-}" ]]; then
  echo "uso: deploy <sha do commit> <usuario do github>" >&2
  exit 2
fi

cd "$dir"
owner="$(sed -n 's/^GHCR_OWNER=//p' .env)"
previous="$(sed -n 's/^CAURI_API_TAG=//p' .env)"
image="ghcr.io/${owner:?GHCR_OWNER faltando em $dir/.env}/cauri-api"

# Credencial do GHCR só durante este deploy, numa pasta temporária.
DOCKER_CONFIG="$(mktemp -d)"
export DOCKER_CONFIG
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
docker login ghcr.io -u "$actor" --password-stdin >/dev/null

# A variável do ambiente vence a do .env; a tag só é gravada depois que a API subiu.
export CAURI_API_TAG="$tag"
docker compose pull --quiet api
docker compose up -d api
printf 'GHCR_OWNER=%s\nCAURI_API_TAG=%s\n' "$owner" "$tag" > .env

# Guarda a versão atual e a anterior (para voltar rápido); apaga as outras.
docker images "$image" --format '{{.Tag}}' | { grep -vxF -e "$tag" -e "${previous:-$tag}" || true; } \
  | while read -r old; do docker rmi "$image:$old" >/dev/null || true; done

echo "API em $tag (antes: ${previous:-nenhuma})"
