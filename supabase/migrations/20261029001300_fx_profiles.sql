-- Cripto e arquivos de qualquer formato:
-- 1. PTAX de venda (SGS série 1) para converter operações em dólar e stablecoins.
-- 2. Moeda e valor originais guardados no movimento convertido para reais.
-- 3. Perfis de importação: o mapeamento de colunas que o usuário fez para um arquivo que o
--    Cauri não reconhecia. Guardam só nomes de colunas e opções, nunca conteúdo do arquivo.

alter type market.indicator_series add value if not exists 'PTAX_VENDA';

-- Moeda original ------------------------------------------------------------------------
-- orig_value é o preço unitário (compra e venda) ou o valor (provento) na moeda original.
-- fx_rate é quantos reais vale 1 unidade dessa moeda em fx_date: PTAX de venda para dólar e
-- stablecoins, fechamento do dia para outra cripto. fx_date anterior à data da operação
-- quer dizer que não havia cotação no dia (fim de semana, feriado) e valeu a última.
-- fee_asset e fee_quantity: a taxa como foi paga (0,0001 BNB, 0,03 USDT), já somada em fees.
alter table ledger.movements
  add column orig_currency text,
  add column orig_value    numeric(28, 10),
  add column fx_rate       numeric(28, 10),
  add column fx_date       date,
  add column fx_source     text,
  add column fee_asset     text,
  add column fee_quantity  numeric(28, 10),
  add constraint movements_orig_currency check (orig_currency ~ '^[A-Z0-9]{2,12}$'),
  add constraint movements_fee_asset check (fee_asset ~ '^[A-Z0-9]{2,12}$'),
  add constraint movements_fx_source check (fx_source in ('ptax', 'fechamento')),
  add constraint movements_fx_complete check (
    num_nonnulls(orig_currency, orig_value, fx_rate, fx_date, fx_source) in (0, 5)
    and (fx_rate is null or fx_rate > 0)
  ),
  add constraint movements_fee_complete check (
    (fee_asset is null) = (fee_quantity is null) and (fee_quantity is null or fee_quantity > 0)
  );

-- A view ganha as colunas novas no fim (create or replace só permite acrescentar).
create or replace view marts.movements with (security_invoker = true) as
select
  m.id,
  m.trade_date,
  m.type,
  m.income_kind,
  m.asset_class,
  m.asset_id,
  m.instrument_id,
  coalesce(a.ticker, i.label) as asset_label,
  coalesce(a.name, i.issuer_name) as asset_name,
  m.quantity,
  m.unit_price,
  m.fees,
  m.amount,
  m.factor,
  i.kind as fi_kind,
  i.rate_pct as fi_rate_pct,
  i.maturity_date as fi_maturity_date,
  m.broker_id,
  b.name as broker_name,
  m.origin,
  m.origin_label,
  m.notes,
  m.version,
  m.created_at,
  m.updated_at,
  m.voided_at,
  m.void_reason,
  m.orig_currency,
  m.orig_value,
  m.fx_rate,
  m.fx_date,
  m.fx_source,
  m.fee_asset,
  m.fee_quantity
from ledger.movements m
left join market.assets a on a.id = m.asset_id
left join ledger.fi_instruments i on i.id = m.instrument_id
left join market.brokers b on b.id = m.broker_id;

-- Perfis de importação --------------------------------------------------------------------
-- mapping: campo do ledger -> nome da coluna no arquivo ({"data": "Data da operação"}).
-- options: corretora fixa, formato de data e de número, moeda padrão. Nada do conteúdo.
create table imports.profiles (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users (id) on delete restrict,
  name          text not null check (length(btrim(name)) between 1 and 80),
  mapping       jsonb not null check (jsonb_typeof(mapping) = 'object'),
  options       jsonb not null default '{}' check (jsonb_typeof(options) = 'object'),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  last_used_at  timestamptz,
  unique (user_id, name),
  constraint profiles_no_cpf check ((mapping::text || options::text) !~ '\d{3}\.\d{3}\.\d{3}-\d{2}')
);

alter table imports.profiles enable row level security;
-- Perfil é configuração, não histórico: pode ser apagado.
grant select, insert, update, delete on imports.profiles to authenticated;

create policy profiles_own_select on imports.profiles
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy profiles_own_insert on imports.profiles
  for insert to authenticated
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy profiles_own_update on imports.profiles
  for update to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy profiles_own_delete on imports.profiles
  for delete to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
