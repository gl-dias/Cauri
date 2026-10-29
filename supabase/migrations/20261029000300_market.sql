-- market: dados de mercado compartilhados (curated). Não pertencem a nenhum usuário.

create table market.issuers (
  code  text primary key,               -- raiz de 4 letras da B3: PETR, ITUB, ITSA
  name  text not null,
  constraint issuers_code_format check (code ~ '^[A-Z0-9]{2,12}$')
);

create table market.assets (
  id             uuid primary key default gen_random_uuid(),
  ticker         text not null unique,  -- PETR4, HGLG11, BTC, TESOURO-IPCA-2029
  class          market.asset_class not null,
  issuer_code    text references market.issuers (code),
  name           text not null,
  provider_ids   jsonb not null default '{}',   -- {"brapi": "PETR4", "coingecko": "bitcoin", ...}
  maturity_date  date,                           -- Tesouro
  active         boolean not null default true,
  created_at     timestamptz not null default now(),
  constraint assets_ticker_format check (ticker ~ '^[A-Z0-9][A-Z0-9.\-]{0,39}$'),
  constraint assets_no_private_fixed_income check (class <> 'renda_fixa')
);
create index assets_issuer_idx on market.assets (issuer_code);

-- Apelidos para o assistente: apontam para um emissor (empresa) ou para um ativo.
create table market.asset_aliases (
  alias_norm   text primary key,        -- minúsculo, sem acento: "itau", "itausa", "bb"
  issuer_code  text references market.issuers (code),
  asset_id     uuid references market.assets (id),
  constraint aliases_one_target check (num_nonnulls(issuer_code, asset_id) = 1),
  constraint aliases_normalized check (alias_norm = lower(alias_norm))
);

create table market.brokers (
  id    text primary key,               -- slug: xp, btg, nubank
  name  text not null unique,
  kind  market.broker_kind not null,
  constraint brokers_id_format check (id ~ '^[a-z0-9][a-z0-9-]*$')
);

create table market.prices_daily (
  asset_id     uuid not null references market.assets (id),
  price_date   date not null,
  currency     market.currency not null default 'BRL',
  close        numeric(28, 10) not null check (close > 0),
  source       text not null,
  run_id       uuid,
  ingested_at  timestamptz not null default now(),
  primary key (asset_id, price_date, currency)
);

create table market.indicators (
  series    market.indicator_series not null,
  ref_date  date not null,
  value     numeric(20, 10) not null,
  unit      text not null,              -- '% a.d.', '% a.a.', '% a.m.'
  run_id    uuid,
  primary key (series, ref_date)
);

create table market.calendar (
  day      date primary key,
  b3_open  boolean not null
);

-- Ativos referenciados pela carteira demo. É o único recorte de mercado que o anon vê:
-- a lista completa de ativos rastreados vem das carteiras reais e revelaria o que os
-- usuários têm. Definida aqui e preenchida de verdade depois que o ledger existir.
create function market.demo_asset_ids() returns setof uuid
language sql stable security definer set search_path = '' as $$
  select null::uuid where false
$$;

create function market.demo_broker_ids() returns setof text
language sql stable security definer set search_path = '' as $$
  select null::text where false
$$;

revoke execute on function market.demo_asset_ids(), market.demo_broker_ids() from public;
grant execute on function market.demo_asset_ids(), market.demo_broker_ids() to anon, authenticated;

-- RLS ------------------------------------------------------------------------------

alter table market.issuers enable row level security;
alter table market.assets enable row level security;
alter table market.asset_aliases enable row level security;
alter table market.brokers enable row level security;
alter table market.prices_daily enable row level security;
alter table market.indicators enable row level security;
alter table market.calendar enable row level security;

grant select on all tables in schema market to authenticated, anon;
grant select, insert, update, delete on all tables in schema market to cauri_ingest;

-- Membros leem tudo do mercado.
create policy issuers_member_select on market.issuers
  for select to authenticated using ((select app.is_member()));
create policy assets_member_select on market.assets
  for select to authenticated using ((select app.is_member()));
create policy aliases_member_select on market.asset_aliases
  for select to authenticated using ((select app.is_member()));
create policy brokers_member_select on market.brokers
  for select to authenticated using ((select app.is_member()));
create policy prices_member_select on market.prices_daily
  for select to authenticated using ((select app.is_member()));
create policy indicators_member_select on market.indicators
  for select to authenticated using ((select app.is_member()));
create policy calendar_member_select on market.calendar
  for select to authenticated using ((select app.is_member()));

-- anon (/demo): só o que a carteira demo referencia + dados públicos não derivados de
-- usuários (indicadores do BCB e calendário).
create policy assets_demo_select on market.assets
  for select to anon using (id in (select market.demo_asset_ids()));
create policy brokers_demo_select on market.brokers
  for select to anon using (id in (select market.demo_broker_ids()));
create policy prices_demo_select on market.prices_daily
  for select to anon using (asset_id in (select market.demo_asset_ids()));
create policy indicators_public_select on market.indicators
  for select to anon using (true);
create policy calendar_public_select on market.calendar
  for select to anon using (true);

-- Jobs escrevem tudo.
create policy issuers_ingest_all on market.issuers
  for all to cauri_ingest using (true) with check (true);
create policy assets_ingest_all on market.assets
  for all to cauri_ingest using (true) with check (true);
create policy aliases_ingest_all on market.asset_aliases
  for all to cauri_ingest using (true) with check (true);
create policy brokers_ingest_all on market.brokers
  for all to cauri_ingest using (true) with check (true);
create policy prices_ingest_all on market.prices_daily
  for all to cauri_ingest using (true) with check (true);
create policy indicators_ingest_all on market.indicators
  for all to cauri_ingest using (true) with check (true);
create policy calendar_ingest_all on market.calendar
  for all to cauri_ingest using (true) with check (true);
