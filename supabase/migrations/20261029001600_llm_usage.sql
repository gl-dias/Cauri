-- Proteção de custo do assistente: uma linha por chamada paga (Haiku, Whisper), com os
-- tokens ou o tamanho do áudio. Serve para o limite diário por usuário e para o Admin
-- acompanhar o gasto. Nada do conteúdo da frase ou do áudio fica aqui.

create table ops.llm_usage (
  id             bigint generated always as identity primary key,
  user_id        uuid not null references auth.users (id) on delete restrict,
  at             timestamptz not null default now(),
  day            date not null default ((now() at time zone 'America/Sao_Paulo')::date),
  provider       text not null check (provider in ('anthropic', 'groq', 'regras')),
  kind           text not null check (kind in ('mensagem', 'transcricao')),
  model          text not null check (length(model) between 1 and 80),
  input_tokens   integer not null default 0 check (input_tokens >= 0),
  output_tokens  integer not null default 0 check (output_tokens >= 0),
  audio_bytes    integer not null default 0 check (audio_bytes >= 0),
  ok             boolean not null
);
create index llm_usage_user_day_idx on ops.llm_usage (user_id, day, kind);
create index llm_usage_day_idx on ops.llm_usage (day);

alter table ops.llm_usage enable row level security;
grant select, insert on ops.llm_usage to authenticated;

-- O próprio usuário grava e conta as suas chamadas (para o limite diário); o admin vê tudo.
create policy llm_usage_own_insert on ops.llm_usage
  for insert to authenticated
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy llm_usage_own_select on ops.llm_usage
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy llm_usage_admin_select on ops.llm_usage
  for select to authenticated
  using ((select app.is_admin()));

-- O admin já vê os e-mails da allowlist; ver o nome de cada convidado no uso é coerente.
create policy profiles_admin_select on app.profiles
  for select to authenticated
  using ((select app.is_admin()));

-- Últimos 30 dias, por dia e por tipo de chamada.
create view marts.llm_usage_daily with (security_invoker = true) as
select
  u.day,
  u.provider,
  u.kind,
  count(*)::int as calls,
  count(*) filter (where not u.ok)::int as failures,
  count(distinct u.user_id)::int as users,
  coalesce(sum(u.input_tokens), 0)::bigint as input_tokens,
  coalesce(sum(u.output_tokens), 0)::bigint as output_tokens,
  coalesce(sum(u.audio_bytes), 0)::bigint as audio_bytes
from ops.llm_usage u
where u.day >= ((now() at time zone 'America/Sao_Paulo')::date - 30)
group by u.day, u.provider, u.kind;

-- Últimos 30 dias, por usuário.
create view marts.llm_usage_users with (security_invoker = true) as
select
  u.user_id,
  coalesce(p.display_name, 'sem nome') as display_name,
  count(*) filter (where u.kind = 'mensagem')::int as messages,
  count(*) filter (where u.kind = 'transcricao')::int as transcriptions,
  coalesce(sum(u.input_tokens + u.output_tokens), 0)::bigint as tokens,
  max(u.at) as last_at
from ops.llm_usage u
left join app.profiles p on p.user_id = u.user_id
where u.day >= ((now() at time zone 'America/Sao_Paulo')::date - 30)
group by u.user_id, p.display_name;

grant select on marts.llm_usage_daily, marts.llm_usage_users to authenticated;
