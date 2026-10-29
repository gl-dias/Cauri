-- marts: views de leitura dos dashboards (Início, Carteira). Todas com security_invoker:
-- o RLS das tabelas de baixo decide o que cada um vê (membro, só o próprio; anon, só o
-- demo). Nenhuma escreve nada.

-- Série diária da carteira: patrimônio, fluxos, cota (TWR) e índices de referência.
create view marts.portfolio_daily with (security_invoker = true) as
select
  s.user_id,
  s.snap_date,
  s.market_value,
  s.cost_basis,
  s.net_flows,
  s.income,
  s.quota_value,
  s.cdi_index,
  s.ipca_index,
  s.stale_count
from engine.portfolio_snapshots s;

-- Série diária por classe de ativo e por corretora (cota própria de cada recorte).
create view marts.buckets_daily with (security_invoker = true) as
select
  b.user_id,
  b.snap_date,
  b.bucket_kind,
  b.bucket_key,
  b.market_value,
  b.cost_basis,
  b.net_flows,
  b.income,
  b.quota_value
from engine.bucket_snapshots b;

-- Posições no último snapshot de cada carteira.
create view marts.positions_current with (security_invoker = true) as
with last_day as (
  select user_id, max(snap_date) as snap_date
  from engine.portfolio_snapshots
  group by user_id
)
select
  p.user_id,
  p.snap_date,
  p.asset_class,
  p.broker_id,
  br.name as broker_name,
  p.asset_id,
  p.instrument_id,
  coalesce(a.ticker, i.label) as label,
  coalesce(a.name, i.issuer_name) as name,
  i.kind as fi_kind,
  i.rate_pct as fi_rate_pct,
  i.maturity_date as fi_maturity_date,
  p.quantity,
  p.avg_cost,
  p.cost_basis,
  p.price,
  p.price_date,
  p.price_status,
  p.market_value,
  p.realized_pnl,
  p.income_cum
from engine.position_snapshots p
join last_day l on l.user_id = p.user_id and l.snap_date = p.snap_date
left join market.assets a on a.id = p.asset_id
left join ledger.fi_instruments i on i.id = p.instrument_id
left join market.brokers br on br.id = p.broker_id;

-- Agenda: proventos já lançados com data futura e vencimentos de renda fixa em carteira.
-- (Sem fonte gratuita de proventos anunciados no v1.)
create view marts.agenda with (security_invoker = true) as
select
  m.user_id,
  'provento'::text as kind,
  m.trade_date as event_date,
  coalesce(a.ticker, i.label) as label,
  m.amount,
  m.income_kind::text as detail,
  m.broker_id
from ledger.movements m
left join market.assets a on a.id = m.asset_id
left join ledger.fi_instruments i on i.id = m.instrument_id
where m.voided_at is null
  and m.type = 'provento'
  and m.trade_date > (now() at time zone 'America/Sao_Paulo')::date
union all
select
  pc.user_id,
  'vencimento'::text as kind,
  pc.fi_maturity_date as event_date,
  pc.label,
  pc.market_value as amount,
  pc.fi_kind::text as detail,
  pc.broker_id
from marts.positions_current pc
where pc.instrument_id is not null
  and pc.fi_maturity_date >= (now() at time zone 'America/Sao_Paulo')::date;

-- Meta de patrimônio (anel "Meta").
create view marts.goal with (security_invoker = true) as
select g.user_id, g.target_amount, g.target_date
from app.goals g;

grant select on marts.portfolio_daily, marts.buckets_daily, marts.positions_current,
  marts.agenda, marts.goal to anon, authenticated;
