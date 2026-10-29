-- raw: respostas cruas das fontes de mercado. ops: log de cada execução dos jobs.

create table raw.market_payloads (
  id              uuid primary key default gen_random_uuid(),
  run_id          uuid,
  source          text not null,                 -- brapi, bcb_sgs, coingecko, tesouro, cotahist
  request         jsonb not null,                -- url e parâmetros, nunca o token
  http_status     integer,
  payload         jsonb,
  payload_sha256  text,
  fetched_at      timestamptz not null default now()
);
create index market_payloads_source_idx on raw.market_payloads (source, fetched_at desc);

create table ops.job_runs (
  id           uuid primary key default gen_random_uuid(),
  job          text not null,                    -- daily, backfill, seed_demo, recalc
  trigger      text not null check (trigger in ('cron', 'manual')),
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  status       ops.run_status not null default 'running',
  git_sha      text,
  details      jsonb not null default '{}'
);
create index job_runs_job_idx on ops.job_runs (job, started_at desc);

create table ops.source_status (
  run_id        uuid not null references ops.job_runs (id) on delete cascade,
  source        text not null,
  status        ops.source_result not null,
  requested     integer not null default 0,
  succeeded     integer not null default 0,
  failed        integer not null default 0,
  error_sample  text,
  duration_ms   integer,
  primary key (run_id, source)
);

create table ops.quota_usage (
  source  text not null,
  month   date not null check (extract(day from month) = 1),
  used    integer not null default 0,
  primary key (source, month)
);

alter table raw.market_payloads enable row level security;
alter table ops.job_runs enable row level security;
alter table ops.source_status enable row level security;
alter table ops.quota_usage enable row level security;

grant select, insert, delete on raw.market_payloads to cauri_ingest;
grant select, insert, update on ops.job_runs, ops.source_status, ops.quota_usage to cauri_ingest;
grant usage on schema ops to authenticated;
grant select on ops.job_runs, ops.source_status, ops.quota_usage to authenticated;

create policy payloads_ingest_all on raw.market_payloads
  for all to cauri_ingest using (true) with check (true);

create policy job_runs_ingest_all on ops.job_runs
  for all to cauri_ingest using (true) with check (true);
create policy source_status_ingest_all on ops.source_status
  for all to cauri_ingest using (true) with check (true);
create policy quota_ingest_all on ops.quota_usage
  for all to cauri_ingest using (true) with check (true);

-- Admin acompanha as execuções pela tela de Admin.
create policy job_runs_admin_select on ops.job_runs
  for select to authenticated using ((select app.is_admin()));
create policy source_status_admin_select on ops.source_status
  for select to authenticated using ((select app.is_admin()));
create policy quota_admin_select on ops.quota_usage
  for select to authenticated using ((select app.is_admin()));
