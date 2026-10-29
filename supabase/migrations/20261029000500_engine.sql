-- engine: snapshots diários por usuário (marts materializado) e fila de recálculo.

create table engine.position_snapshots (
  id             bigint generated always as identity primary key,
  user_id        uuid not null references auth.users (id) on delete cascade,
  snap_date      date not null,
  asset_id       uuid references market.assets (id),
  instrument_id  uuid references ledger.fi_instruments (id),
  broker_id      text not null references market.brokers (id),
  asset_class    market.asset_class not null,
  quantity       numeric(28, 10),               -- null em renda fixa
  avg_cost       numeric(28, 10),               -- preço médio consolidado do ativo
  cost_basis     numeric(20, 2) not null,
  price          numeric(28, 10),
  price_date     date,                          -- data do preço usado (ou até quando o CDI rendeu)
  price_status   engine.price_status not null,
  market_value   numeric(20, 2) not null,       -- renda fixa: valor bruto
  realized_pnl   numeric(20, 2) not null default 0,
  income_cum     numeric(20, 2) not null default 0,
  constraint position_one_target check (num_nonnulls(asset_id, instrument_id) = 1),
  unique nulls not distinct (user_id, snap_date, asset_id, instrument_id, broker_id)
);
create index position_snapshots_user_date_idx on engine.position_snapshots (user_id, snap_date);

create table engine.portfolio_snapshots (
  user_id       uuid not null references auth.users (id) on delete cascade,
  snap_date     date not null,
  market_value  numeric(20, 2) not null,
  cost_basis    numeric(20, 2) not null,
  net_flows     numeric(20, 2) not null,        -- aportes e compras menos resgates, vendas e proventos
  income        numeric(20, 2) not null default 0,
  quota_value   numeric(28, 12) not null,       -- cota (TWR), começa em 1
  cdi_index     numeric(28, 16) not null,       -- CDI acumulado desde o início, começa em 1
  ipca_index    numeric(28, 16) not null,
  stale_count   integer not null default 0,
  computed_at   timestamptz not null default now(),
  primary key (user_id, snap_date)
);

-- Menor data afetada por mudanças no ledger ainda não recalculada.
create table engine.dirty_ranges (
  user_id       uuid primary key references auth.users (id) on delete cascade,
  from_date     date not null,
  requested_at  timestamptz not null default now()
);

create function engine.mark_dirty() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_from date := new.trade_date;
begin
  if tg_op = 'UPDATE' then
    v_from := least(old.trade_date, new.trade_date);
  end if;
  insert into engine.dirty_ranges (user_id, from_date)
  values (new.user_id, v_from)
  on conflict (user_id) do update
    set from_date = least(engine.dirty_ranges.from_date, excluded.from_date),
        requested_at = now();
  return null;
end
$$;

revoke execute on function engine.mark_dirty() from public, anon, authenticated;

create trigger movements_mark_dirty
  after insert or update on ledger.movements
  for each row execute function engine.mark_dirty();

-- RLS ------------------------------------------------------------------------------

alter table engine.position_snapshots enable row level security;
alter table engine.portfolio_snapshots enable row level security;
alter table engine.dirty_ranges enable row level security;

-- A API recalcula os snapshots do próprio usuário logo depois de gravar no ledger.
grant select, insert, update, delete on engine.position_snapshots, engine.portfolio_snapshots
  to authenticated;
grant select, delete on engine.dirty_ranges to authenticated;
grant select on engine.position_snapshots, engine.portfolio_snapshots to anon;
grant select, insert, update, delete on all tables in schema engine to cauri_ingest;

create policy positions_own_all on engine.position_snapshots
  for all to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy positions_demo_select on engine.position_snapshots
  for select to anon using (user_id = (select app.demo_user_id()));
create policy positions_ingest_all on engine.position_snapshots
  for all to cauri_ingest using (true) with check (true);

create policy portfolio_own_all on engine.portfolio_snapshots
  for all to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy portfolio_demo_select on engine.portfolio_snapshots
  for select to anon using (user_id = (select app.demo_user_id()));
create policy portfolio_ingest_all on engine.portfolio_snapshots
  for all to cauri_ingest using (true) with check (true);

create policy dirty_own on engine.dirty_ranges
  for all to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy dirty_ingest_all on engine.dirty_ranges
  for all to cauri_ingest using (true) with check (true);
