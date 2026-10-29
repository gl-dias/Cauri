-- engine: snapshots por classe de ativo e por corretora (cota própria de cada recorte),
-- para a rentabilidade por classe e por corretora. Mesmo recorte de acesso das outras
-- tabelas de snapshot.

create table engine.bucket_snapshots (
  user_id       uuid not null references auth.users (id) on delete cascade,
  snap_date     date not null,
  bucket_kind   text not null check (bucket_kind in ('class', 'broker')),
  bucket_key    text not null,                  -- 'acao', 'fii'... ou o id da corretora
  market_value  numeric(20, 2) not null,
  cost_basis    numeric(20, 2) not null,
  net_flows     numeric(20, 2) not null,
  income        numeric(20, 2) not null default 0,
  quota_value   numeric(28, 12) not null,
  primary key (user_id, snap_date, bucket_kind, bucket_key)
);

alter table engine.bucket_snapshots enable row level security;

grant select, insert, update, delete on engine.bucket_snapshots to authenticated;
grant select on engine.bucket_snapshots to anon;
grant select, insert, update, delete on engine.bucket_snapshots to cauri_ingest;

create policy buckets_own_all on engine.bucket_snapshots
  for all to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy buckets_demo_select on engine.bucket_snapshots
  for select to anon using (user_id = (select app.demo_user_id()));
create policy buckets_ingest_all on engine.bucket_snapshots
  for all to cauri_ingest using (true) with check (true);
