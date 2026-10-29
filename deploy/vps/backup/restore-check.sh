#!/usr/bin/env bash
# Teste de restauração do backup do Cauri. NUNCA aponte para produção: o banco de destino
# é apagado e recriado.
#
# Simula a restauração num projeto novo do Supabase:
#   1. banco limpo com todas as migrations (no Supabase local: `supabase db reset`);
#   2. contas recriadas com o mesmo id e e-mail, a partir do CSV mínimo do backup;
#   3. dados restaurados com pg_restore (só dados, com os triggers desligados pela sessão
#      durante a carga, porque o ledger tem travas de escrita que não fazem sentido numa
#      restauração);
#   4. contagem de linhas comparada com o manifesto do backup.
#
# Uso (no computador de desenvolvimento, com o Supabase local no ar):
#   deploy/vps/backup/restore-check.sh /caminho/cauri-AAAA-MM-DD.dump
#
# Variáveis: CAURI_RESTORE_DATABASE_URL (padrão: o Postgres do Supabase local) e
# CAURI_RESTORE_SKIP_RESET=1 para pular o reset (quando o banco já está limpo).
set -euo pipefail

DUMP="${1:?informe o arquivo .dump}"
DIR="$(cd "$(dirname "$DUMP")" && pwd)"
NAME="$(basename "$DUMP" .dump)"
TARGET="${CAURI_RESTORE_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:54322/postgres}"
PG_IMAGE="${CAURI_PG_IMAGE:-postgres:17-alpine}"

case "$TARGET" in
  *@127.0.0.1:*|*@localhost:*|*@host.docker.internal:*) ;;
  *) echo "recusado: o teste de restauração só roda contra um banco local" >&2; exit 2 ;;
esac

# No Windows (Git Bash), o Docker quer o caminho no formato do Windows.
HOST_DIR="$(cygpath -w "$DIR" 2>/dev/null || echo "$DIR")"

pg() {
  MSYS_NO_PATHCONV=1 docker run --rm --network host -e PGURL="$TARGET" -v "$HOST_DIR:/in:ro" \
    "$PG_IMAGE" sh -c "$1"
}

if [ "${CAURI_RESTORE_SKIP_RESET:-}" != "1" ]; then
  echo "1/4 banco limpo com as migrations"
  (cd "$(git rev-parse --show-toplevel)" && npx --yes supabase@2.122.0 db reset --local >/dev/null)
fi

echo "2/4 contas com o mesmo id e e-mail"
pg "psql \"\$PGURL\" -v ON_ERROR_STOP=1 -q <<'SQL'
create temp table restore_users (id uuid, email text, created_at timestamptz);
\\copy restore_users from '/in/$NAME-usuarios.csv' csv header
-- O Auth lê as colunas de token como texto: precisam ser vazias, não nulas.
insert into auth.users (id, instance_id, aud, role, email, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
  confirmation_token, recovery_token, email_change_token_new, email_change,
  email_change_token_current, phone_change, phone_change_token, reauthentication_token)
select id, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', email,
  created_at, '{\"provider\": \"email\", \"providers\": [\"email\"]}', '{}', created_at, now(),
  '', '', '', '', '', '', '', ''
from restore_users on conflict (id) do nothing;
insert into auth.identities (id, user_id, provider_id, provider, identity_data, created_at, updated_at)
select gen_random_uuid(), id, id::text, 'email',
  jsonb_build_object('sub', id::text, 'email', email, 'email_verified', true), created_at, now()
from restore_users on conflict do nothing;
SQL"

echo "3/4 dados"
# O reset e as migrations já criaram linhas de referência; a restauração substitui tudo.
# Os triggers ficam desligados só nesta sessão (o ledger proíbe remoção física no uso normal).
pg "psql \"\$PGURL\" -v ON_ERROR_STOP=1 -qAt -c \"
  select 'set session_replication_role = replica; truncate '
    || string_agg(format('%I.%I', schemaname, tablename), ', ') || ' cascade;'
  from pg_tables where schemaname in ('app','ledger','imports','assistant','market','engine','ops')
\" | psql \"\$PGURL\" -v ON_ERROR_STOP=1 -q"
# Carga com os triggers desligados pela sessão (replica): no Supabase o postgres não é
# superusuário, não desliga triggers de chave estrangeira com --disable-triggers e só pode
# mudar session_replication_role dentro da sessão. O pg_restore gera o SQL e o psql aplica.
pg "{ echo 'set session_replication_role = replica;'; pg_restore --data-only --no-owner --file=- /in/$NAME.dump; } | psql \"\$PGURL\" -v ON_ERROR_STOP=1 -q >/dev/null"

echo "4/4 contagens"
expected="$DIR/$NAME-contagens.txt"
actual="$(mktemp)"
pg "psql \"\$PGURL\" -v ON_ERROR_STOP=1 -qAt -c \"
  select format('select %L || '';'' || count(*) from %I.%I;', schemaname || '.' || tablename, schemaname, tablename)
  from pg_tables where schemaname in ('app','ledger','imports','assistant','market','engine','ops') order by 1
\" | psql \"\$PGURL\" -v ON_ERROR_STOP=1 -qAt" > "$actual"
if diff -u "$expected" "$actual"; then
  echo "restauração conferida: $(wc -l < "$actual") tabelas com as mesmas contagens do backup"
else
  echo "contagens diferentes do backup (acima)" >&2
  exit 1
fi
