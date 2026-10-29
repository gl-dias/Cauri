-- ledger: fonte única de verdade das movimentações, por usuário.
--
-- Invariantes garantidas aqui (o Python valida antes só para dar erro amigável):
--   * nunca se apaga uma movimentação: remover = preencher voided_at (soft delete);
--   * todo insert/update gera uma linha de auditoria em movement_history;
--   * a posição de um ativo nunca fica negativa em nenhum ponto da linha do tempo;
--   * toda mudança marca engine.dirty_ranges para o recálculo dos snapshots.
--
-- Códigos de erro próprios (SQLSTATE), mapeados para mensagens na API (CA007 fica em app):
--   CA001 venda maior que a posição      CA002 campo imutável alterado
--   CA003 remoção física proibida         CA004 combinação inválida de campos
--   CA005 data no futuro                  CA006 movimentação removida não se edita

create table ledger.fi_instruments (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users (id) on delete restrict,
  kind           ledger.fi_kind not null,
  issuer_name    text not null check (length(btrim(issuer_name)) > 0),
  indexer        text not null default 'CDI' check (indexer = 'CDI'),
  rate_pct       numeric(9, 4) not null check (rate_pct > 0 and rate_pct <= 1000),  -- 110 = 110% do CDI
  maturity_date  date not null,
  broker_id      text not null references market.brokers (id),
  label          text not null check (length(btrim(label)) > 0),
  created_at     timestamptz not null default now(),
  unique (user_id, id),
  unique (user_id, kind, issuer_name, rate_pct, maturity_date, broker_id)
);

create table ledger.movements (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references auth.users (id) on delete restrict,
  trade_date       date not null check (trade_date >= date '1990-01-01'),
  asset_id         uuid references market.assets (id),
  instrument_id    uuid,
  asset_class      market.asset_class not null,   -- derivado do ativo pelo trigger
  type             ledger.movement_type not null,
  income_kind      ledger.income_kind,
  quantity         numeric(28, 10),
  unit_price       numeric(28, 10),
  fees             numeric(20, 2) not null default 0 check (fees >= 0),
  amount           numeric(20, 2),
  factor           numeric(20, 10),
  broker_id        text not null references market.brokers (id),
  origin           ledger.origin not null,
  origin_ref       uuid,                            -- lote de importação, proposta do chat...
  origin_label     text,                            -- "Planilha XP", "Manual", "Chat"
  idempotency_key  text not null check (length(idempotency_key) between 8 and 200),
  notes            text,
  version          integer not null default 1,
  created_at       timestamptz not null default now(),
  created_by       uuid default auth.uid(),
  updated_at       timestamptz not null default now(),
  updated_by       uuid,
  voided_at        timestamptz,
  voided_by        uuid,
  void_reason      text,

  unique (user_id, idempotency_key),
  foreign key (user_id, instrument_id) references ledger.fi_instruments (user_id, id),

  constraint movements_one_target check (num_nonnulls(asset_id, instrument_id) = 1),
  constraint movements_income_kind check ((type = 'provento') = (income_kind is not null)),
  constraint movements_fees_only_trades check (type in ('compra', 'venda') or fees = 0),
  constraint movements_void_reason check (
    (voided_at is null and void_reason is null)
    or (voided_at is not null and length(btrim(coalesce(void_reason, ''))) > 0)
  ),
  -- Formato de cada tipo. coalesce(..., false): em CHECK, NULL passaria como verdadeiro.
  constraint movements_shape check (coalesce(case type
    when 'compra' then
      asset_id is not null and quantity > 0 and unit_price >= 0 and amount is null and factor is null
    when 'venda' then
      asset_id is not null and quantity > 0 and unit_price >= 0 and amount is null and factor is null
    when 'aporte' then
      instrument_id is not null and amount > 0 and quantity is null and unit_price is null and factor is null
    when 'resgate' then
      instrument_id is not null and amount > 0 and quantity is null and unit_price is null and factor is null
    when 'provento' then
      amount > 0 and quantity is null and unit_price is null and factor is null
    when 'desdobramento' then
      asset_id is not null and factor > 1 and quantity is null and unit_price is null and amount is null
    when 'grupamento' then
      asset_id is not null and factor > 0 and factor < 1 and quantity is null and unit_price is null and amount is null
    when 'bonificacao' then
      asset_id is not null and factor > 0 and unit_price >= 0 and quantity is null and amount is null
  end, false))
);

create index movements_user_date_idx on ledger.movements (user_id, trade_date);
create index movements_user_asset_idx on ledger.movements (user_id, asset_id, trade_date)
  where asset_id is not null;
create index movements_asset_idx on ledger.movements (asset_id) where asset_id is not null;
create index movements_instrument_idx on ledger.movements (instrument_id) where instrument_id is not null;

create table ledger.movement_history (
  id           bigint generated always as identity primary key,
  movement_id  uuid not null references ledger.movements (id),
  user_id      uuid not null,
  version      integer not null,
  op           text not null check (op in ('insert', 'update', 'void', 'restore')),
  before       jsonb,
  after        jsonb not null,
  actor        uuid,
  reason       text,
  at           timestamptz not null default now()
);
create index movement_history_movement_idx on ledger.movement_history (movement_id, version);
create index movement_history_user_idx on ledger.movement_history (user_id, at desc);

-- Normalização e regras antes de gravar -------------------------------------------

create function ledger.movements_before_write() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_class market.asset_class;
  v_today date := (now() at time zone 'America/Sao_Paulo')::date;
begin
  if tg_op = 'UPDATE' then
    if new.id <> old.id or new.user_id <> old.user_id or new.origin <> old.origin
       or new.origin_ref is distinct from old.origin_ref
       or new.idempotency_key <> old.idempotency_key
       or new.created_at <> old.created_at
       or new.created_by is distinct from old.created_by then
      raise exception 'Campo imutável da movimentação foi alterado.' using errcode = 'CA002';
    end if;
    if old.voided_at is not null and new.voided_at is not null then
      raise exception 'Movimentação removida não pode ser editada.' using errcode = 'CA006';
    end if;
    new.version := old.version + 1;
    new.updated_at := now();
    new.updated_by := auth.uid();
    if new.voided_at is not null and old.voided_at is null then
      new.voided_by := coalesce(auth.uid(), new.voided_by);
    end if;
    if new.voided_at is null and old.voided_at is not null then
      new.voided_by := null;
    end if;
  else
    new.version := 1;
    new.created_at := now();
    new.updated_at := new.created_at;
    new.voided_at := null;
    new.voided_by := null;
    new.void_reason := null;
  end if;

  -- Classe vem do ativo (ou do instrumento de renda fixa), nunca do cliente.
  if new.instrument_id is not null then
    v_class := 'renda_fixa';
  else
    select a.class into v_class from market.assets a where a.id = new.asset_id;
  end if;
  new.asset_class := v_class;

  if v_class = 'renda_fixa' and new.type not in ('aporte', 'resgate', 'provento') then
    raise exception 'Renda fixa aceita só aporte, resgate e provento.' using errcode = 'CA004';
  end if;
  if v_class <> 'renda_fixa' and new.type in ('aporte', 'resgate') then
    raise exception 'Aporte e resgate são só para renda fixa.' using errcode = 'CA004';
  end if;
  if new.type in ('desdobramento', 'grupamento', 'bonificacao') and v_class not in ('acao', 'fii') then
    raise exception 'Eventos corporativos são só para ações e FIIs.' using errcode = 'CA004';
  end if;

  -- Só provento pode ter data futura (agenda de pagamentos já anunciados).
  if new.type <> 'provento' and new.trade_date > v_today then
    raise exception 'Data da movimentação no futuro.' using errcode = 'CA005';
  end if;

  return new;
end
$$;

create trigger movements_before_write
  before insert or update on ledger.movements
  for each row execute function ledger.movements_before_write();

-- Remoção física proibida (soft delete via voided_at) ------------------------------

create function ledger.forbid_delete() returns trigger
language plpgsql as $$
begin
  raise exception 'Remoção física proibida em %.%; use voided_at.', tg_table_schema, tg_table_name
    using errcode = 'CA003';
end
$$;

create trigger movements_forbid_delete
  before delete on ledger.movements
  for each row execute function ledger.forbid_delete();
create trigger movements_forbid_truncate
  before truncate on ledger.movements
  for each statement execute function ledger.forbid_delete();
create trigger history_forbid_delete
  before delete or update on ledger.movement_history
  for each row execute function ledger.forbid_delete();
create trigger history_forbid_truncate
  before truncate on ledger.movement_history
  for each statement execute function ledger.forbid_delete();
create trigger instruments_forbid_delete
  before delete on ledger.fi_instruments
  for each row execute function ledger.forbid_delete();

-- Auditoria ------------------------------------------------------------------------

create function ledger.movements_audit() returns trigger
language plpgsql security definer set search_path = '' as $$
declare
  v_op text;
  v_reason text;
begin
  if tg_op = 'INSERT' then
    v_op := 'insert';
  elsif new.voided_at is not null and old.voided_at is null then
    v_op := 'void';
    v_reason := new.void_reason;
  elsif new.voided_at is null and old.voided_at is not null then
    v_op := 'restore';
  else
    v_op := 'update';
  end if;
  v_reason := coalesce(v_reason, nullif(current_setting('cauri.change_reason', true), ''));

  insert into ledger.movement_history (movement_id, user_id, version, op, before, after, actor, reason)
  values (
    new.id, new.user_id, new.version, v_op,
    case when tg_op = 'UPDATE' then to_jsonb(old) end,
    to_jsonb(new),
    auth.uid(),
    v_reason
  );
  return null;
end
$$;

create trigger movements_audit
  after insert or update on ledger.movements
  for each row execute function ledger.movements_audit();

-- Posição nunca negativa -----------------------------------------------------------
-- Percorre a linha do tempo do ativo. Dentro do mesmo dia: eventos corporativos
-- primeiro (data ex), depois compras, depois vendas. Roda no commit (diferido), então
-- um lote inteiro é validado depois de todas as linhas entrarem.

create function ledger.assert_position_ok(p_user uuid, p_asset uuid) returns void
language plpgsql security definer set search_path = '' as $$
declare
  r record;
  v_qty numeric := 0;
  v_ticker text;
begin
  -- Serializa as validações do mesmo usuário: duas transações concorrentes não passam
  -- cada uma sozinha e estouram juntas.
  perform pg_advisory_xact_lock(hashtextextended('cauri:ledger:' || p_user::text, 0));

  for r in
    select m.trade_date, m.type, m.quantity, m.factor
    from ledger.movements m
    where m.user_id = p_user and m.asset_id = p_asset and m.voided_at is null
      and m.type in ('compra', 'venda', 'desdobramento', 'grupamento', 'bonificacao')
    order by m.trade_date,
      case m.type when 'compra' then 1 when 'venda' then 2 else 0 end,
      m.created_at, m.id
  loop
    case r.type
      when 'compra' then v_qty := v_qty + r.quantity;
      when 'venda' then v_qty := v_qty - r.quantity;
      when 'desdobramento', 'grupamento' then v_qty := v_qty * r.factor;
      when 'bonificacao' then v_qty := v_qty + v_qty * r.factor;
      else null;
    end case;
    if v_qty < 0 then
      select a.ticker into v_ticker from market.assets a where a.id = p_asset;
      raise exception 'Venda de % maior que a posição em %.', v_ticker, to_char(r.trade_date, 'DD/MM/YYYY')
        using errcode = 'CA001',
              detail = json_build_object('asset_id', p_asset, 'ticker', v_ticker,
                                         'date', r.trade_date, 'shortfall', -v_qty)::text;
    end if;
  end loop;
end
$$;

create function ledger.movements_position_check() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.asset_id is not null then
    perform ledger.assert_position_ok(new.user_id, new.asset_id);
  end if;
  if tg_op = 'UPDATE' and old.asset_id is not null and old.asset_id is distinct from new.asset_id then
    perform ledger.assert_position_ok(old.user_id, old.asset_id);
  end if;
  return null;
end
$$;

create constraint trigger movements_position_check
  after insert or update on ledger.movements
  deferrable initially deferred
  for each row execute function ledger.movements_position_check();

revoke execute on function ledger.movements_before_write(), ledger.forbid_delete(),
  ledger.movements_audit(), ledger.assert_position_ok(uuid, uuid),
  ledger.movements_position_check() from public, anon, authenticated;

-- Demo: agora que o ledger existe, define o recorte de mercado visível ao anon ------

create or replace function market.demo_asset_ids() returns setof uuid
language sql stable security definer set search_path = '' as $$
  select distinct m.asset_id from ledger.movements m
  where m.user_id = app.demo_user_id() and m.asset_id is not null
$$;

create or replace function market.demo_broker_ids() returns setof text
language sql stable security definer set search_path = '' as $$
  select m.broker_id from ledger.movements m where m.user_id = app.demo_user_id()
  union
  select i.broker_id from ledger.fi_instruments i where i.user_id = app.demo_user_id()
$$;

-- RLS ------------------------------------------------------------------------------

alter table ledger.fi_instruments enable row level security;
alter table ledger.movements enable row level security;
alter table ledger.movement_history enable row level security;

-- Escrita só pela API (schema não exposto no PostgREST). Nenhum role recebe DELETE.
grant select, insert, update on ledger.fi_instruments, ledger.movements to authenticated;
grant select on ledger.movement_history to authenticated;
grant select on ledger.fi_instruments, ledger.movements to anon, cauri_ingest;

create policy instruments_own_select on ledger.fi_instruments
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy instruments_own_insert on ledger.fi_instruments
  for insert to authenticated
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy instruments_own_update on ledger.fi_instruments
  for update to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy instruments_demo_select on ledger.fi_instruments
  for select to anon using (user_id = (select app.demo_user_id()));
create policy instruments_ingest_select on ledger.fi_instruments
  for select to cauri_ingest using (true);

create policy movements_own_select on ledger.movements
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy movements_own_insert on ledger.movements
  for insert to authenticated
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy movements_own_update on ledger.movements
  for update to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy movements_demo_select on ledger.movements
  for select to anon using (user_id = (select app.demo_user_id()));
create policy movements_ingest_select on ledger.movements
  for select to cauri_ingest using (true);

create policy history_own_select on ledger.movement_history
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
