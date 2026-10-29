-- marts: o contrato de leitura do front. Únicas relações expostas pelo PostgREST.
-- Todas as views usam security_invoker: quem consulta passa pelo RLS das tabelas de
-- baixo, então membro vê só o próprio e o anon vê só o demo.
-- As views de dashboard (posições, alocação, evolução, KPIs, agenda) entram com os
-- snapshots na Fase 2.

create view marts.me with (security_invoker = true) as
select
  p.user_id,
  p.display_name,
  app.current_role_name() as role
from app.profiles p
where p.user_id = coalesce(auth.uid(), app.demo_user_id());

create view marts.movements with (security_invoker = true) as
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
  m.void_reason
from ledger.movements m
left join market.assets a on a.id = m.asset_id
left join ledger.fi_instruments i on i.id = m.instrument_id
left join market.brokers b on b.id = m.broker_id;

-- Autocomplete de ticker (membros veem a lista toda; o anon, só os ativos do demo).
create view marts.assets with (security_invoker = true) as
select a.id, a.ticker, a.name, a.class, a.issuer_code, a.maturity_date
from market.assets a
where a.active;

create view marts.brokers with (security_invoker = true) as
select b.id, b.name, b.kind
from market.brokers b;

create view marts.fi_instruments with (security_invoker = true) as
select i.id, i.kind, i.issuer_name, i.rate_pct, i.maturity_date, i.broker_id, i.label
from ledger.fi_instruments i;

grant usage on schema marts to anon, authenticated;
grant select on all tables in schema marts to anon, authenticated;
