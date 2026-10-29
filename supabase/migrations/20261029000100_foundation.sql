-- Fundação: extensões, schemas, roles de serviço e tipos compartilhados.
-- Cada módulo é dono do seu schema (ver docs/arquitetura.md, seção 3).

-- Não usamos GraphQL. Desligar evita uma segunda porta de leitura sobre o banco.
drop extension if exists pg_graphql;

create schema if not exists app;      -- auth/admin: allowlist, perfis, configurações
create schema if not exists market;   -- curated, compartilhado: ativos, preços, indicadores
create schema if not exists raw;      -- raw, compartilhado: respostas cruas das fontes
create schema if not exists ledger;   -- curated, por usuário: fonte única de verdade
create schema if not exists engine;   -- marts materializado, por usuário: snapshots
create schema if not exists marts;    -- views de leitura expostas pelo PostgREST
create schema if not exists ops;      -- log dos jobs

-- O schema public não é usado e não fica exposto. Tira o acesso padrão dos roles da API.
revoke all on schema public from anon, authenticated;

-- Roles de serviço. As senhas NÃO ficam em migration: em produção são definidas à mão
-- (alter role ... password ...); no ambiente local, em supabase/seed.sql.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'cauri_api') then
    -- A API conecta como cauri_api e, em cada request, faz SET LOCAL ROLE authenticated
    -- com as claims do JWT. noinherit: sozinho, o role não tem privilégio nenhum.
    create role cauri_api with login noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'cauri_ingest') then
    -- Jobs (ingestão de mercado e snapshots). Não escreve no ledger.
    create role cauri_ingest with login;
  end if;
end
$$;

grant authenticated to cauri_api;

-- Tipos compartilhados -------------------------------------------------------------

create type market.asset_class as enum ('acao', 'fii', 'tesouro', 'renda_fixa', 'cripto');
create type market.broker_kind as enum ('corretora', 'banco', 'exchange');
create type market.indicator_series as enum ('CDI', 'SELIC_META', 'SELIC_EFETIVA', 'IPCA');
create type market.currency as enum ('BRL', 'USD');

create type app.app_role as enum ('admin', 'user');

create type ledger.movement_type as enum (
  'compra', 'venda', 'aporte', 'resgate', 'provento',
  'desdobramento', 'grupamento', 'bonificacao'
);
create type ledger.income_kind as enum ('dividendo', 'jcp', 'rendimento', 'juros');
create type ledger.origin as enum ('import', 'manual', 'chat');
create type ledger.fi_kind as enum ('CDB', 'LCI', 'LCA');

create type engine.price_status as enum ('ok', 'stale', 'missing');

create type ops.run_status as enum ('running', 'ok', 'partial', 'failed');
create type ops.source_result as enum ('ok', 'partial', 'failed', 'quota_exceeded', 'skipped');

-- Uso dos schemas ------------------------------------------------------------------
-- Os schemas não expostos no PostgREST (tudo menos marts) só são alcançáveis por
-- conexão SQL direta (API e jobs) ou através das views de marts.

grant usage on schema app, market, ledger, engine, marts to anon, authenticated;
grant usage on schema app, market, raw, ledger, engine, ops to cauri_ingest;
