-- imports: pré-visualização e histórico das importações de planilhas (por usuário).
--
-- O arquivo enviado nunca é guardado, nem o nome dele (pode ter sido renomeado com dados
-- pessoais): o lote guarda um rótulo gerado ("B3 · Movimentação, 01/2025 a 12/2025"), o
-- hash e o tamanho. As linhas ficam reduzidas às colunas que o adaptador lê (data, tipo,
-- ativo, quantidade...), sem CPF e sem nome: o parser nem carrega as outras colunas, e
-- as constraints abaixo são a última linha de defesa.
-- Escrita só pela API, com o RLS do usuário; o schema não é exposto no PostgREST.

create schema if not exists imports;
grant usage on schema imports to authenticated;

create table imports.batches (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users (id) on delete restrict,
  status       text not null default 'preview'
               check (status in ('preview', 'committed', 'discarded')),
  warnings     jsonb not null default '[]',
  created_at   timestamptz not null default now(),
  finished_at  timestamptz,
  constraint batches_finished check ((status = 'preview') = (finished_at is null)),
  unique (user_id, id)
);
create index batches_user_idx on imports.batches (user_id, created_at desc);

create table imports.files (
  id               uuid primary key default gen_random_uuid(),
  batch_id         uuid not null,
  user_id          uuid not null,
  position         integer not null check (position >= 0),  -- ordem no envio
  label            text not null check (length(label) between 1 and 200),
  sha256           text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes       integer not null check (size_bytes > 0),
  adapter          text not null check (adapter ~ '^[a-z0-9-]+$'),
  adapter_version  integer not null check (adapter_version > 0),
  created_at       timestamptz not null default now(),
  foreign key (user_id, batch_id) references imports.batches (user_id, id),
  unique (user_id, id),
  unique (batch_id, position),
  constraint files_no_cpf check (label !~ '\d{3}\.?\d{3}\.?\d{3}-?\d{2}')
);
create index files_batch_idx on imports.files (batch_id);

create table imports.rows (
  id                  uuid primary key default gen_random_uuid(),
  file_id             uuid not null,
  user_id             uuid not null,
  position            integer not null check (position >= 0),  -- ordem na pré-visualização
  line_numbers        integer[] not null,  -- linhas do arquivo (mais de uma quando agrupa)
  raw                 jsonb not null,      -- só as colunas que o adaptador lê, como texto
  draft               jsonb,               -- rascunho da movimentação, quando há uma
  idempotency_key     text,
  status              text not null check (status in
                        ('ok', 'error', 'already_imported', 'possible_duplicate', 'ignored')),
  messages            jsonb not null default '[]',
  match_movement_ids  uuid[] not null default '{}',
  decision            text check (decision in ('import', 'keep_existing', 'replace', 'import_new')),
  movement_id         uuid references ledger.movements (id),
  foreign key (user_id, file_id) references imports.files (user_id, id),
  unique (file_id, position),
  constraint rows_draft_when_importable check (
    status in ('error', 'ignored') or (draft is not null and idempotency_key is not null)
  ),
  constraint rows_no_cpf check (raw::text !~ '\d{3}\.\d{3}\.\d{3}-\d{2}')
);
create index rows_file_idx on imports.rows (file_id, position);

-- Movimentações de um lote (origin_ref aponta para imports.batches.id).
create index movements_origin_ref_idx on ledger.movements (origin_ref) where origin_ref is not null;

-- RLS ------------------------------------------------------------------------------

alter table imports.batches enable row level security;
alter table imports.files enable row level security;
alter table imports.rows enable row level security;

-- Nenhum role recebe DELETE: descartar é mudar o status.
grant select, insert, update on imports.batches, imports.files, imports.rows to authenticated;

create policy batches_own_select on imports.batches
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy batches_own_insert on imports.batches
  for insert to authenticated
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy batches_own_update on imports.batches
  for update to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()) and (select app.is_member()));

create policy files_own_select on imports.files
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy files_own_insert on imports.files
  for insert to authenticated
  with check (user_id = (select auth.uid()) and (select app.is_member()));

create policy rows_own_select on imports.rows
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy rows_own_insert on imports.rows
  for insert to authenticated
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy rows_own_update on imports.rows
  for update to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()) and (select app.is_member()));
