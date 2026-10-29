-- app: allowlist, perfis, configurações, metas e notificações.

create table app.allowlist (
  email     text primary key,
  role      app.app_role not null default 'user',
  note      text,
  added_by  uuid references auth.users (id) on delete set null,
  added_at  timestamptz not null default now(),
  -- Sempre minúsculo: a comparação com o e-mail do JWT é exata.
  constraint allowlist_email_lower check (email = lower(btrim(email))),
  constraint allowlist_email_format check (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$')
);

create table app.profiles (
  user_id       uuid primary key references auth.users (id) on delete cascade,
  display_name  text not null,
  created_at    timestamptz not null default now()
);

-- Configurações globais (ex.: demo_user_id). Lidas por funções security definer.
create table app.settings (
  key    text primary key,
  value  jsonb not null
);

create table app.goals (
  user_id        uuid primary key references auth.users (id) on delete cascade,
  target_amount  numeric(20, 2) not null check (target_amount > 0),
  target_date    date
);

create table app.notifications (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users (id) on delete cascade,
  kind        text not null,
  payload     jsonb not null default '{}',
  created_at  timestamptz not null default now(),
  read_at     timestamptz
);
create index notifications_user_idx on app.notifications (user_id, created_at desc);

-- Funções de acesso ----------------------------------------------------------------
-- security definer + search_path vazio: leem tabelas que o chamador não enxerga, sem
-- abrir brecha de search_path.

create function app.demo_user_id() returns uuid
language sql stable security definer set search_path = '' as $$
  select (value #>> '{}')::uuid from app.settings where key = 'demo_user_id'
$$;

create function app.is_member() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from app.allowlist
    where email = lower(auth.jwt() ->> 'email')
  )
$$;

create function app.is_admin() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from app.allowlist
    where email = lower(auth.jwt() ->> 'email') and role = 'admin'
  )
$$;

-- Papel do usuário corrente: 'admin' | 'user' | 'demo' (anon) | null.
create function app.current_role_name() returns text
language sql stable security definer set search_path = '' as $$
  select case
    when auth.uid() is null then 'demo'
    else (
      select a.role::text from app.allowlist a
      where a.email = lower(auth.jwt() ->> 'email')
    )
  end
$$;

revoke execute on function app.demo_user_id(), app.is_member(), app.is_admin(),
  app.current_role_name() from public;
grant execute on function app.demo_user_id(), app.is_member(), app.is_admin(),
  app.current_role_name() to anon, authenticated, cauri_ingest;

-- Hook de allowlist (Supabase Auth: Before User Created) ---------------------------
-- Recusa a criação de qualquer usuário cujo e-mail não esteja na allowlist. A mensagem
-- é genérica de propósito: não confirma nem nega quem está na lista.

create function app.hook_before_user_created(event jsonb) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare
  v_email text := lower(btrim(event -> 'user' ->> 'email'));
begin
  if v_email is not null and exists (select 1 from app.allowlist where email = v_email) then
    return '{}'::jsonb;
  end if;
  return jsonb_build_object(
    'error', jsonb_build_object(
      'http_code', 403,
      'message', 'Acesso restrito a convidados.'
    )
  );
end
$$;

revoke execute on function app.hook_before_user_created(jsonb) from public, anon, authenticated;
grant usage on schema app to supabase_auth_admin;
grant execute on function app.hook_before_user_created(jsonb) to supabase_auth_admin;

-- Perfil criado no primeiro login (trigger em auth.users) ---------------------------

create function app.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into app.profiles (user_id, display_name)
  values (
    new.id,
    coalesce(nullif(new.raw_user_meta_data ->> 'display_name', ''), split_part(new.email, '@', 1))
  )
  on conflict (user_id) do nothing;
  return new;
end
$$;

revoke execute on function app.handle_new_user() from public, anon, authenticated;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function app.handle_new_user();

-- Nunca deixar o sistema sem admin --------------------------------------------------

create function app.guard_last_admin() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if old.role = 'admin'
     and (tg_op = 'DELETE' or new.role <> 'admin')
     and not exists (
       select 1 from app.allowlist where role = 'admin' and email <> old.email
     ) then
    raise exception 'Não é possível remover o último admin.' using errcode = 'CA007';
  end if;
  return coalesce(new, old);
end
$$;

revoke execute on function app.guard_last_admin() from public, anon, authenticated;

create trigger allowlist_guard_last_admin
  before update or delete on app.allowlist
  for each row execute function app.guard_last_admin();

-- RLS ------------------------------------------------------------------------------

alter table app.allowlist enable row level security;
alter table app.profiles enable row level security;
alter table app.settings enable row level security;
alter table app.goals enable row level security;
alter table app.notifications enable row level security;

-- allowlist: só admin, e sempre via API.
grant select, insert, update, delete on app.allowlist to authenticated;
create policy allowlist_admin_all on app.allowlist
  for all to authenticated
  using ((select app.is_admin()))
  with check ((select app.is_admin()));

-- perfis: o próprio; o anon vê só o perfil demo.
grant select, update (display_name) on app.profiles to authenticated;
grant select on app.profiles to anon;
create policy profiles_own_select on app.profiles
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy profiles_own_update on app.profiles
  for update to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()));
create policy profiles_demo_select on app.profiles
  for select to anon
  using (user_id = (select app.demo_user_id()));

-- settings: ninguém lê direto; acesso só pelas funções acima.
grant select on app.settings to cauri_ingest;
create policy settings_ingest_select on app.settings
  for select to cauri_ingest using (true);

-- metas
grant select, insert, update, delete on app.goals to authenticated;
grant select on app.goals to anon;
create policy goals_own_all on app.goals
  for all to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()) and (select app.is_member()));
create policy goals_demo_select on app.goals
  for select to anon
  using (user_id = (select app.demo_user_id()));

-- notificações
grant select, update (read_at) on app.notifications to authenticated;
grant insert on app.notifications to cauri_ingest;
create policy notifications_own_select on app.notifications
  for select to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()));
create policy notifications_own_update on app.notifications
  for update to authenticated
  using (user_id = (select auth.uid()) and (select app.is_member()))
  with check (user_id = (select auth.uid()));
create policy notifications_ingest_insert on app.notifications
  for insert to cauri_ingest with check (true);
