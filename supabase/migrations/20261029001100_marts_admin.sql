-- marts: log dos jobs para a tela de Admin. O RLS de ops só deixa o admin ler (as
-- policies checam app.is_admin()); o anon nem recebe permissão nestas views.

create view marts.job_runs with (security_invoker = true) as
select r.id, r.job, r.trigger, r.started_at, r.finished_at, r.status, r.details
from ops.job_runs r;

create view marts.job_sources with (security_invoker = true) as
select s.run_id, s.source, s.status, s.requested, s.succeeded, s.failed, s.error_sample, s.duration_ms
from ops.source_status s;

grant select on marts.job_runs, marts.job_sources to authenticated;
