-- assistant: conversas com o assistente de lançamentos (por usuário).
--
-- O LLM só recebe a frase e a data de hoje, nunca a carteira. Ele devolve {tipo, ativo
-- como falado, quantidade, preço, moeda, data}; a resolução do ativo, a regra de
-- ambiguidade e a conferência no ledger são Python determinístico. Nada vai para o ledger
-- sem o usuário confirmar o cartão. Escrita só pela API, com o RLS do usuário.

create schema if not exists assistant;
grant usage on schema assistant to authenticated;

create table assistant.conversations (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users (id) on delete restrict,
  title       text not null check (length(btrim(title)) between 1 and 120),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (user_id, id)
);
create index conversations_user_idx on assistant.conversations (user_id, updated_at desc);

create table assistant.messages (
  id               uuid primary key default gen_random_uuid(),
  conversation_id  uuid not null,
  user_id          uuid not null,
  role             text not null check (role in ('user', 'assistant')),
  content          text not null check (length(content) between 1 and 4000),
  input_mode       text check (input_mode in ('texto', 'voz')),
  llm_model        text,
  llm_output       jsonb,   -- o que o LLM extraiu da frase (nada da carteira)
  -- clock_timestamp: a pergunta e a resposta entram na mesma transação e precisam de ordem.
  created_at       timestamptz not null default clock_timestamp(),
  foreign key (user_id, conversation_id) references assistant.conversations (user_id, id),
  unique (user_id, id)
);
create index messages_conversation_idx on assistant.messages (conversation_id, created_at);

-- A proposta é o cartão de confirmação: os itens (rascunhos já resolvidos, perguntas,
-- preço sugerido, conferência no ledger) ficam juntos em jsonb, porque são poucos e mudam
-- juntos a cada resposta ou edição.
create table assistant.proposals (
  id           uuid primary key default gen_random_uuid(),
  message_id   uuid not null,
  user_id      uuid not null,
  status       text not null default 'pending'
               check (status in ('pending', 'confirmed', 'cancelled')),
  items        jsonb not null default '[]' check (jsonb_typeof(items) = 'array'),
  suggestions  jsonb not null default '[]' check (jsonb_typeof(suggestions) = 'array'),
  created_at   timestamptz not null default now(),
  finished_at  timestamptz,
  constraint proposals_finished check ((status = 'pending') = (finished_at is null)),
  foreign key (user_id, message_id) references assistant.messages (user_id, id)
);
create index proposals_message_idx on assistant.proposals (message_id);

alter table assistant.conversations enable row level security;
alter table assistant.messages enable row level security;
alter table assistant.proposals enable row level security;

-- Nenhum role recebe DELETE: o histórico da conversa fica.
grant select, insert, update on assistant.conversations, assistant.messages, assistant.proposals
  to authenticated;

create policy conversations_own_select on assistant.conversations
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy conversations_own_insert on assistant.conversations
  for insert to authenticated
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy conversations_own_update on assistant.conversations
  for update to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()) and (select app.is_member()));

create policy messages_own_select on assistant.messages
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy messages_own_insert on assistant.messages
  for insert to authenticated
  with check (user_id = (select auth.uid()) and (select app.is_member()));

create policy proposals_own_select on assistant.proposals
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy proposals_own_insert on assistant.proposals
  for insert to authenticated
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy proposals_own_update on assistant.proposals
  for update to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()) and (select app.is_member()));
