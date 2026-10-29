-- Isolamento: um usuário não lê dados de outro, o demo não lê dados reais, e os roles
-- de serviço só fazem o que precisam. Tudo roda numa transação desfeita no final e não
-- depende do que já existe no banco (o demo real, ativos sincronizados etc.).
begin;
create extension if not exists pgtap with schema extensions;
select plan(60);

-- Fixtures (como postgres) ---------------------------------------------------------
-- ana: admin; bruno: usuário; carla: tinha acesso e foi removida; demo: usuário demo.
insert into auth.users (id, instance_id, aud, role, email, raw_user_meta_data, created_at, updated_at)
values
  ('00000000-0000-4000-8000-00000000000a', '00000000-0000-0000-0000-000000000000',
   'authenticated', 'authenticated', 'ana@example.test', '{"display_name":"Ana"}', now(), now()),
  ('00000000-0000-4000-8000-00000000000b', '00000000-0000-0000-0000-000000000000',
   'authenticated', 'authenticated', 'bruno@example.test', '{}', now(), now()),
  ('00000000-0000-4000-8000-00000000000c', '00000000-0000-0000-0000-000000000000',
   'authenticated', 'authenticated', 'carla@example.test', '{}', now(), now()),
  ('00000000-0000-4000-8000-0000000000dd', '00000000-0000-0000-0000-000000000000',
   'authenticated', 'authenticated', 'demo-teste@cauri.invalid', '{"display_name":"Investidor Demo"}', now(), now());

insert into app.allowlist (email, role) values
  ('ana@example.test', 'admin'),
  ('bruno@example.test', 'user');

-- Nesta transação, o demo é o usuário de teste (o demo real deixa de ser "o demo").
insert into app.settings (key, value) values
  ('demo_user_id', '"00000000-0000-4000-8000-0000000000dd"')
on conflict (key) do update set value = excluded.value;

insert into market.brokers (id, name, kind) values
  ('corretora-a', 'Corretora A', 'corretora'),
  ('corretora-b', 'Corretora B', 'corretora'),
  ('corretora-demo', 'Corretora Demo', 'corretora');
insert into market.issuers (code, name) values ('AAAA', 'Empresa A'), ('BBBB', 'Empresa B'), ('DDDD', 'Empresa D');
insert into market.assets (id, ticker, class, issuer_code, name) values
  ('10000000-0000-4000-8000-000000000001', 'AAAA3', 'acao', 'AAAA', 'Empresa A ON'),
  ('10000000-0000-4000-8000-000000000002', 'BBBB4', 'acao', 'BBBB', 'Empresa B PN'),
  ('10000000-0000-4000-8000-000000000004', 'DDDD3', 'acao', 'DDDD', 'Empresa D ON');
insert into market.indicators (series, ref_date, value, unit) values
  ('CDI', date '2026-10-01', 0.05, '% a.d.')
on conflict (series, ref_date) do nothing;

insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key)
values
  ('00000000-0000-4000-8000-00000000000a', date '2026-01-10', '10000000-0000-4000-8000-000000000001',
   'compra', 10, 20, 'corretora-a', 'manual', 'fixture-ana-1'),
  ('00000000-0000-4000-8000-00000000000a', date '2026-02-10', '10000000-0000-4000-8000-000000000001',
   'compra', 5, 22, 'corretora-a', 'manual', 'fixture-ana-2'),
  ('00000000-0000-4000-8000-00000000000b', date '2026-01-15', '10000000-0000-4000-8000-000000000002',
   'compra', 7, 30, 'corretora-b', 'manual', 'fixture-bruno-1'),
  ('00000000-0000-4000-8000-00000000000c', date '2026-01-20', '10000000-0000-4000-8000-000000000002',
   'compra', 3, 31, 'corretora-b', 'manual', 'fixture-carla-1'),
  ('00000000-0000-4000-8000-0000000000dd', date '2026-03-01', '10000000-0000-4000-8000-000000000004',
   'compra', 100, 10, 'corretora-demo', 'manual', 'fixture-demo-1');

insert into engine.bucket_snapshots (user_id, snap_date, bucket_kind, bucket_key, market_value, cost_basis, net_flows, quota_value)
values
  ('00000000-0000-4000-8000-00000000000a', date '2026-10-01', 'class', 'acao', 330, 310, 0, 1.06),
  ('00000000-0000-4000-8000-0000000000dd', date '2026-10-01', 'class', 'acao', 1100, 1000, 0, 1.1);

insert into engine.portfolio_snapshots (user_id, snap_date, market_value, cost_basis, net_flows, quota_value, cdi_index, ipca_index)
values
  ('00000000-0000-4000-8000-00000000000a', date '2026-10-01', 330, 310, 0, 1.06, 1.1, 1.04),
  ('00000000-0000-4000-8000-0000000000dd', date '2026-10-01', 1100, 1000, 0, 1.1, 1.1, 1.04);

insert into ops.job_runs (job, trigger, status) values ('daily', 'cron', 'ok');

insert into imports.batches (id, user_id) values
  ('20000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-00000000000a');
insert into imports.files (id, batch_id, user_id, position, label, sha256, size_bytes, adapter, adapter_version)
values ('20000000-0000-4000-8000-000000000002', '20000000-0000-4000-8000-000000000001',
        '00000000-0000-4000-8000-00000000000a', 0, 'Template do Cauri', repeat('a', 64), 10, 'planilha', 1);
insert into imports.rows (file_id, user_id, position, line_numbers, raw, status)
values ('20000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-00000000000a', 0, '{2}',
        '{"ativo": "AAAA3"}', 'error');
insert into assistant.conversations (id, user_id, title) values
  ('30000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-00000000000a', 'Conversa da ana');
insert into assistant.messages (id, conversation_id, user_id, role, content) values
  ('30000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000001',
   '00000000-0000-4000-8000-00000000000a', 'user', 'comprei 3 petrobras');
insert into assistant.proposals (message_id, user_id) values
  ('30000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-00000000000a');
insert into ops.llm_usage (user_id, provider, kind, model, input_tokens, output_tokens, ok) values
  ('00000000-0000-4000-8000-00000000000a', 'anthropic', 'mensagem', 'claude-haiku-5-5', 800, 90, true),
  ('00000000-0000-4000-8000-00000000000b', 'anthropic', 'mensagem', 'claude-haiku-5-5', 700, 80, true);
insert into imports.profiles (user_id, name, mapping, options)
values ('00000000-0000-4000-8000-00000000000a', 'Corretora da Ana',
        '{"data": "Data", "tipo": "Operação", "ativo": "Papel"}', '{"broker_id": "corretora-a"}');

-- ana (membro, admin) ---------------------------------------------------------------
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"00000000-0000-4000-8000-00000000000a","email":"ana@example.test","role":"authenticated"}', true);

select is((select count(*)::int from ledger.movements), 2, 'ana vê só as 2 movimentações dela');
select is((select count(*)::int from ledger.movements where user_id <> auth.uid()), 0,
  'ana não vê movimentações de outros');
select is((select count(*)::int from marts.movements), 2, 'marts.movements da ana tem só as dela');
select is((select count(*)::int from engine.portfolio_snapshots), 1, 'ana vê só o próprio snapshot');
select is((select count(*)::int from engine.bucket_snapshots), 1, 'ana vê só os próprios snapshots por classe');
select is((select count(*)::int from app.allowlist where email like '%@example.test' and email in ('ana@example.test', 'bruno@example.test')), 2,
  'admin lê a allowlist');
select is((select role from marts.me), 'admin', 'marts.me da ana diz admin');
select ok((select count(*) from marts.job_runs) >= 1, 'admin lê o log de jobs pela view');
select is((select count(*)::int from market.assets where ticker in ('AAAA3', 'BBBB4', 'DDDD3')), 3,
  'membro lê todos os ativos');
select is((select count(*)::int from imports.rows), 1, 'ana vê as linhas da própria importação');
select throws_ok($$delete from imports.batches$$, '42501', null,
  'ninguém apaga lote de importação (descartar é mudar o status)');
select is((select count(*)::int from imports.profiles), 1, 'ana vê o próprio perfil de importação');
select ok((select count(distinct user_id) from ops.llm_usage) >= 2, 'admin vê o uso do assistente de todos');
select is((select count(*)::int from assistant.messages) + (select count(*)::int from assistant.proposals), 2,
  'ana vê a própria conversa com o assistente');
select throws_ok($$delete from assistant.messages$$, '42501', null, 'ninguém apaga mensagem do assistente');

select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key)
    values ('00000000-0000-4000-8000-00000000000b', date '2026-03-01', '10000000-0000-4000-8000-000000000002',
            'compra', 1, 1, 'corretora-b', 'manual', 'ana-tenta-bruno')$$,
  '42501', null, 'ana não consegue gravar movimentação em nome do bruno');

-- Update em linha de outro usuário não dá erro: o RLS simplesmente não encontra a linha.
update ledger.movements set notes = 'invadido'
where user_id = '00000000-0000-4000-8000-00000000000b';

reset role;
select is((select count(*)::int from ledger.movements where notes = 'invadido'), 0,
  'ana não consegue editar movimentação do bruno');

-- bruno (membro comum) --------------------------------------------------------------
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"00000000-0000-4000-8000-00000000000b","email":"bruno@example.test","role":"authenticated"}', true);

select is((select count(*)::int from ledger.movements), 1, 'bruno vê só a movimentação dele');
select is((select count(*)::int from app.allowlist), 0, 'usuário comum não lê a allowlist');
select is((select role from marts.me), 'user', 'marts.me do bruno diz user');
select throws_ok(
  $$insert into app.allowlist (email) values ('intruso@example.test')$$,
  '42501', null, 'usuário comum não adiciona e-mail na allowlist');
select is((select count(*)::int from ops.job_runs), 0, 'usuário comum não lê o log de jobs');
select is((select count(*)::int from marts.job_runs), 0, 'usuário comum não lê o log de jobs pela view');
select is((select count(*)::int from imports.batches) + (select count(*)::int from imports.rows), 0,
  'bruno não vê a importação da ana');
select throws_ok(
  $$insert into imports.batches (user_id) values ('00000000-0000-4000-8000-00000000000a')$$,
  '42501', null, 'bruno não cria lote de importação em nome da ana');
select is((select count(*)::int from imports.profiles), 0, 'bruno não vê o perfil da ana');
select is((select count(*)::int from ops.llm_usage where user_id <> auth.uid()), 0,
  'usuário comum só vê o próprio uso do assistente');
select throws_ok(
  $$insert into ops.llm_usage (user_id, provider, kind, model, ok)
    values ('00000000-0000-4000-8000-00000000000a', 'anthropic', 'mensagem', 'x', true)$$,
  '42501', null, 'bruno não registra uso em nome da ana');
select is((select count(*)::int from assistant.conversations) + (select count(*)::int from assistant.proposals), 0,
  'bruno não vê a conversa da ana com o assistente');
select throws_ok(
  $$insert into assistant.conversations (user_id, title) values ('00000000-0000-4000-8000-00000000000a', 'x')$$,
  '42501', null, 'bruno não cria conversa em nome da ana');
select throws_ok(
  $$insert into imports.profiles (user_id, name, mapping) values
    ('00000000-0000-4000-8000-00000000000a', 'Intruso', '{}')$$,
  '42501', null, 'bruno não cria perfil em nome da ana');
delete from imports.profiles where name = 'Corretora da Ana';

reset role;

-- carla: removida da allowlist, ainda tem dados -------------------------------------
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"00000000-0000-4000-8000-00000000000c","email":"carla@example.test","role":"authenticated"}', true);

select is((select count(*)::int from ledger.movements), 0, 'quem saiu da allowlist perde acesso na hora');
select is((select count(*)::int from market.assets), 0, 'quem saiu da allowlist não lê mercado');
select throws_ok(
  $$insert into imports.batches (user_id) values ('00000000-0000-4000-8000-00000000000c')$$,
  '42501', null, 'quem saiu da allowlist não importa');
select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key)
    values ('00000000-0000-4000-8000-00000000000c', date '2026-03-01', '10000000-0000-4000-8000-000000000002',
            'compra', 1, 1, 'corretora-b', 'manual', 'carla-pos-remocao')$$,
  '42501', null, 'quem saiu da allowlist não grava');

reset role;

-- JWT com o id do usuário demo (ele não está na allowlist) --------------------------
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"00000000-0000-4000-8000-0000000000dd","email":"demo-teste@cauri.invalid","role":"authenticated"}', true);

select is((select count(*)::int from ledger.movements), 0, 'sessão autenticada do demo não lê nada');

reset role;

-- anon (/demo) ----------------------------------------------------------------------
set local role anon;
select set_config('request.jwt.claims', '{"role":"anon"}', true);

select is((select count(*)::int from ledger.movements), 1, 'anon vê só a movimentação do demo');
select is((select count(*)::int from ledger.movements where user_id <> app.demo_user_id()), 0,
  'anon não vê movimentação real');
select is((select count(*)::int from marts.movements), 1, 'marts.movements do anon tem só o demo');
select is((select array_agg(ticker)::text from market.assets), '{DDDD3}',
  'anon só vê ativos da carteira demo (a lista rastreada vazaria carteiras reais)');
select is((select count(*)::int from market.brokers), 1, 'anon só vê corretoras usadas pelo demo');
select is((select count(*)::int from engine.portfolio_snapshots), 1, 'anon vê só o snapshot do demo');
select is((select count(*)::int from engine.bucket_snapshots where user_id <> app.demo_user_id()), 0,
  'anon não vê snapshot por classe de carteira real');
select ok((select count(*) from market.indicators) > 0, 'anon lê indicadores públicos');
select is((select display_name from marts.me), 'Investidor Demo', 'marts.me do anon é o perfil demo');
select is((select count(*)::int from marts.portfolio_daily where user_id <> app.demo_user_id()), 0,
  'marts.portfolio_daily do anon não tem carteira real');
select is((select count(*)::int from marts.buckets_daily where user_id <> app.demo_user_id()), 0,
  'marts.buckets_daily do anon não tem carteira real');
select is((select count(*)::int from marts.positions_current where user_id <> app.demo_user_id()), 0,
  'marts.positions_current do anon não tem carteira real');
select throws_ok($$select count(*) from app.allowlist$$, '42501', null, 'anon não lê a allowlist');
select throws_ok($$select count(*) from marts.job_runs$$, '42501', null, 'anon não lê o log de jobs');
select throws_ok($$select count(*) from imports.rows$$, '42501', null, 'anon não alcança as importações');
select throws_ok($$select count(*) from imports.profiles$$, '42501', null, 'anon não alcança os perfis');
select throws_ok($$select count(*) from assistant.messages$$, '42501', null, 'anon não alcança o assistente');
select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key)
    values ('00000000-0000-4000-8000-0000000000dd', date '2026-03-02', '10000000-0000-4000-8000-000000000004',
            'compra', 1, 1, 'corretora-demo', 'manual', 'anon-escreve')$$,
  '42501', null, 'anon não grava nada, nem no demo');

reset role;

select is((select count(*)::int from imports.profiles where name = 'Corretora da Ana'), 1,
  'bruno não apaga o perfil da ana');

-- Defesa no banco: CPF formatado não entra no raw de uma linha importada.
select throws_ok(
  $$insert into imports.rows (file_id, user_id, position, line_numbers, raw, status)
    values ('20000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-00000000000a', 1, '{3}',
            '{"obs": "cpf 123.456.789-00"}', 'error')$$,
  '23514', null, 'CPF no raw de uma linha importada é recusado pelo banco');

-- cauri_ingest (job) ----------------------------------------------------------------
-- O postgres criou o role (tem ADMIN OPTION), mas precisa da associação para assumir.
grant cauri_ingest to postgres;
grant usage on schema extensions to cauri_ingest;  -- só para enxergar as funções do pgTAP
set local role cauri_ingest;

select lives_ok(
  $$insert into market.prices_daily (asset_id, price_date, close, source)
    values ('10000000-0000-4000-8000-000000000001', date '2026-10-01', 21.5, 'teste')$$,
  'job grava preço de mercado');
select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key)
    values ('00000000-0000-4000-8000-00000000000a', date '2026-03-01', '10000000-0000-4000-8000-000000000001',
            'compra', 1, 1, 'corretora-a', 'manual', 'job-escreve-ledger')$$,
  '42501', null, 'job não escreve no ledger');

reset role;

-- Hook de allowlist -----------------------------------------------------------------
select is(
  app.hook_before_user_created('{"user":{"email":"Ana@Example.test"}}'::jsonb), '{}'::jsonb,
  'hook deixa passar e-mail da allowlist (sem diferenciar maiúsculas)');
select is(
  app.hook_before_user_created('{"user":{"email":"estranho@example.test"}}'::jsonb) #>> '{error,http_code}', '403',
  'hook recusa e-mail fora da allowlist');

select * from finish();
rollback;
