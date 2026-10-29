-- Invariantes do ledger garantidas pelo banco, independentemente de quem escreve.
begin;
create extension if not exists pgtap with schema extensions;
select plan(26);

insert into auth.users (id, instance_id, aud, role, email, raw_user_meta_data, created_at, updated_at)
values ('00000000-0000-4000-8000-00000000000a', '00000000-0000-0000-0000-000000000000',
        'authenticated', 'authenticated', 'ana@example.test', '{}', now(), now());
insert into app.allowlist (email, role) values ('ana@example.test', 'admin');
insert into market.brokers (id, name, kind) values ('corretora-a', 'Corretora A', 'corretora');
insert into market.issuers (code, name) values ('AAAA', 'Empresa A');
insert into market.assets (id, ticker, class, issuer_code, name) values
  ('10000000-0000-4000-8000-000000000001', 'AAAA3', 'acao', 'AAAA', 'Empresa A ON'),
  ('10000000-0000-4000-8000-000000000009', 'CRIP', 'cripto', null, 'Cripto X');

-- A validação de posição é diferida para o commit; aqui forçamos a checagem imediata
-- para enxergar o erro dentro do teste.
set constraints ledger.movements_position_check immediate;

set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"00000000-0000-4000-8000-00000000000a","email":"ana@example.test","role":"authenticated"}', true);

-- Formato e combinações -------------------------------------------------------------
select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, unit_price, broker_id, origin, idempotency_key)
    values (auth.uid(), date '2026-01-05', '10000000-0000-4000-8000-000000000001', 'compra', 10, 'corretora-a', 'manual', 'sem-quantidade')$$,
  '23514', null, 'compra sem quantidade é recusada');

select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key, opening_balance)
    values (auth.uid(), date '2026-01-05', '10000000-0000-4000-8000-000000000001', 'venda', 1, 10, 'corretora-a', 'manual', 'saldo-em-venda', true)$$,
  '23514', null, 'saldo inicial só existe como compra');

select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key, orig_currency)
    values (auth.uid(), date '2026-01-05', '10000000-0000-4000-8000-000000000001', 'compra', 1, 10, 'corretora-a', 'manual', 'moeda-pela-metade', 'USDT')$$,
  '23514', null, 'moeda original sem cotação é recusada');

select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key)
    values (auth.uid(), current_date + 10, '10000000-0000-4000-8000-000000000001', 'compra', 1, 10, 'corretora-a', 'manual', 'compra-futura')$$,
  'CA005', null, 'compra com data no futuro é recusada');

select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, factor, broker_id, origin, idempotency_key)
    values (auth.uid(), date '2026-01-05', '10000000-0000-4000-8000-000000000009', 'desdobramento', 2, 'corretora-a', 'manual', 'split-cripto')$$,
  'CA004', null, 'evento corporativo em cripto é recusado');

select lives_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, income_kind, amount, broker_id, origin, idempotency_key)
    values (auth.uid(), current_date + 20, '10000000-0000-4000-8000-000000000001', 'provento', 'dividendo', 12.5, 'corretora-a', 'manual', 'provento-anunciado')$$,
  'provento com data futura é aceito (agenda)');

select is(
  (select asset_class::text from ledger.movements where idempotency_key = 'provento-anunciado'),
  'acao', 'classe vem do ativo, preenchida pelo banco');

-- Posição nunca negativa ------------------------------------------------------------
select lives_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, fees, broker_id, origin, idempotency_key)
    values (auth.uid(), date '2026-01-05', '10000000-0000-4000-8000-000000000001', 'compra', 10, 20, 1.50, 'corretora-a', 'manual', 'compra-1')$$,
  'compra de 10');

select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key)
    values (auth.uid(), date '2026-01-06', '10000000-0000-4000-8000-000000000001', 'venda', 11, 25, 'corretora-a', 'manual', 'venda-demais')$$,
  'CA001', null, 'venda maior que a posição é bloqueada');

select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key)
    values (auth.uid(), date '2026-01-04', '10000000-0000-4000-8000-000000000001', 'venda', 1, 25, 'corretora-a', 'manual', 'venda-antes-da-compra')$$,
  'CA001', null, 'venda retroativa anterior à compra é bloqueada');

select lives_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key)
    values
      (auth.uid(), date '2026-01-07', '10000000-0000-4000-8000-000000000001', 'venda', 3, 22, 'corretora-a', 'manual', 'venda-mesmo-dia'),
      (auth.uid(), date '2026-01-07', '10000000-0000-4000-8000-000000000001', 'compra', 3, 21, 'corretora-a', 'manual', 'compra-mesmo-dia')$$,
  'compra e venda no mesmo dia: compras contam primeiro');

select lives_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, factor, broker_id, origin, idempotency_key)
    values (auth.uid(), date '2026-01-10', '10000000-0000-4000-8000-000000000001', 'desdobramento', 2, 'corretora-a', 'manual', 'desdobramento-2')$$,
  'desdobramento 1 para 2');

select lives_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key)
    values (auth.uid(), date '2026-01-11', '10000000-0000-4000-8000-000000000001', 'venda', 15, 12, 'corretora-a', 'manual', 'venda-pos-split')$$,
  'depois do desdobramento dá para vender mais que a quantidade original');

select throws_ok(
  $$update ledger.movements set voided_at = now(), void_reason = 'lançada errado'
    where idempotency_key = 'compra-1'$$,
  'CA001', null, 'remover uma compra antiga que cobre vendas posteriores é bloqueado');

select throws_ok(
  $$update ledger.movements set trade_date = date '2026-01-12' where idempotency_key = 'compra-1'$$,
  'CA001', null, 'mover a compra para depois das vendas é bloqueado');

-- Auditoria, versão e soft delete ---------------------------------------------------
select set_config('cauri.change_reason', 'corrigindo taxa', true);
update ledger.movements set fees = 2.00 where idempotency_key = 'compra-1';

select is((select version from ledger.movements where idempotency_key = 'compra-1'), 2,
  'edição incrementa a versão');
select is(
  (select array_agg(h.op order by h.version)::text from ledger.movement_history h
   join ledger.movements m on m.id = h.movement_id where m.idempotency_key = 'compra-1'),
  '{insert,update}', 'histórico tem insert e update');
select is(
  (select reason from ledger.movement_history h join ledger.movements m on m.id = h.movement_id
   where m.idempotency_key = 'compra-1' and h.op = 'update'),
  'corrigindo taxa', 'motivo da edição fica no histórico');
select is(
  (select (before ->> 'fees')::numeric from ledger.movement_history h join ledger.movements m on m.id = h.movement_id
   where m.idempotency_key = 'compra-1' and h.op = 'update'),
  1.50, 'histórico guarda o valor anterior');

update ledger.movements set voided_at = now(), void_reason = 'duplicada'
  where idempotency_key = 'provento-anunciado';
select is(
  (select op from ledger.movement_history h join ledger.movements m on m.id = h.movement_id
   where m.idempotency_key = 'provento-anunciado' order by h.version desc limit 1),
  'void', 'remoção vira soft delete registrado como void');

select throws_ok(
  $$update ledger.movements set amount = 99 where idempotency_key = 'provento-anunciado'$$,
  'CA006', null, 'movimentação removida não pode ser editada');

select throws_ok(
  $$update ledger.movements set idempotency_key = 'outra-chave' where idempotency_key = 'compra-1'$$,
  'CA002', null, 'campo imutável não pode mudar');

select throws_ok(
  $$insert into ledger.movements (user_id, trade_date, asset_id, type, quantity, unit_price, broker_id, origin, idempotency_key)
    values (auth.uid(), date '2026-01-05', '10000000-0000-4000-8000-000000000001', 'compra', 10, 20, 'corretora-a', 'manual', 'compra-1')$$,
  '23505', null, 'mesma chave de idempotência não duplica');

select is((select from_date from engine.dirty_ranges where user_id = auth.uid()), date '2026-01-05',
  'mudanças marcam o recálculo a partir da menor data afetada');

reset role;

-- Nem o dono das tabelas apaga ------------------------------------------------------
select throws_ok(
  $$delete from ledger.movements where idempotency_key = 'compra-1'$$,
  'CA003', null, 'delete físico é proibido até para o postgres');
select throws_ok(
  $$delete from ledger.movement_history$$,
  'CA003', null, 'histórico de auditoria é só de inserção');

select * from finish();
rollback;
