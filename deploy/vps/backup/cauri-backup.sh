#!/usr/bin/env bash
# Backup semanal do banco de produção do Cauri para a VPS.
#
# - Só os schemas de dados: app, ledger, imports, assistant (do usuário), market, engine e ops.
#   Fica de fora o raw (respostas cruas das fontes, refeitas pelo job) e o auth inteiro.
# - Junto, um CSV mínimo com id e e-mail dos usuários (sem senha, sem token): é o que permite
#   recriar as contas com o mesmo id numa restauração e religar os dados a elas.
# - Um manifesto com a contagem de linhas de cada tabela, para conferir a restauração.
# - Retenção: 8 semanas. Arquivos com permissão 600.
#
# Configuração em /opt/cauri/backup.env (chmod 600):
#   CAURI_BACKUP_DATABASE_URL=postgresql://postgres.<ref>:<senha>@<pooler>.pooler.supabase.com:5432/postgres
# (pooler em modo sessão, porta 5432: o pg_dump precisa de sessão.)
#
# Uso: cauri-backup.sh [pasta]   (padrão: /opt/cauri/backups)
set -euo pipefail

ENV_FILE="${CAURI_BACKUP_ENV:-/opt/cauri/backup.env}"
if [ -z "${CAURI_BACKUP_DATABASE_URL:-}" ] && [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi
: "${CAURI_BACKUP_DATABASE_URL:?defina CAURI_BACKUP_DATABASE_URL (em $ENV_FILE)}"

OUT="${1:-/opt/cauri/backups}"
STAMP="$(date -u +%Y-%m-%d)"
NAME="cauri-$STAMP"
SCHEMAS=(app ledger imports assistant market engine ops)
PG_IMAGE="${CAURI_PG_IMAGE:-postgres:17-alpine}"  # mesma versão maior do Supabase

mkdir -p "$OUT"
chmod 700 "$OUT"
umask 077

schema_args=()
for s in "${SCHEMAS[@]}"; do schema_args+=(--schema="$s"); done
schema_list="$(printf "'%s'," "${SCHEMAS[@]}")"
schema_list="${schema_list%,}"

pg() {
  docker run --rm --network host -e PGURL="$CAURI_BACKUP_DATABASE_URL" -v "$OUT:/out" \
    "$PG_IMAGE" sh -c "$1"
}

# Formato custom: compactado e restaurável tabela a tabela com pg_restore.
pg "pg_dump \"\$PGURL\" --format=custom --no-owner --no-privileges $(printf '%q ' "${schema_args[@]}") --file=/out/$NAME.dump"

pg "psql \"\$PGURL\" -v ON_ERROR_STOP=1 -qAt -c \"\\copy (select id, email, created_at from auth.users order by created_at) to '/out/$NAME-usuarios.csv' csv header\""

# Contagem exata por tabela (as tabelas são pequenas; count(*) basta).
pg "psql \"\$PGURL\" -v ON_ERROR_STOP=1 -qAt -c \"
  select format('select %L || '';'' || count(*) from %I.%I;', schemaname || '.' || tablename, schemaname, tablename)
  from pg_tables where schemaname in ($schema_list) order by 1
\" | psql \"\$PGURL\" -v ON_ERROR_STOP=1 -qAt > /out/$NAME-contagens.txt"

chmod 600 "$OUT/$NAME".* "$OUT/$NAME"-*
echo "backup: $OUT/$NAME.dump ($(du -h "$OUT/$NAME.dump" | cut -f1)), $(wc -l < "$OUT/$NAME-contagens.txt") tabelas"

# Retenção de 8 semanas.
find "$OUT" -maxdepth 1 -name 'cauri-*' -mtime +56 -print -delete
