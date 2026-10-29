# ADR 0001: leitura direto no Supabase, escrita pela API

Status: aceita (29/10/2026)

## Contexto

O front é estático (Cloudflare Pages) e o banco está no Supabase. Importação de
planilhas e o assistente precisam de Python sob demanda, então existe uma API. A
dúvida era se os dashboards também deveriam passar por ela. Se passassem, o `/demo`
público e as telas do `/app` dependeriam da API estar no ar, e o filtro de acesso
ficaria duplicado (código da API e RLS).

## Decisão

- Os dashboards leem as views do schema `marts` direto pelo PostgREST do Supabase.
  É o único schema exposto (`supabase/config.toml`, `api.schemas = ["marts"]`), e
  todas as views usam `security_invoker`, então o RLS das tabelas de baixo vale.
- A FastAPI recebe só escrita (os fluxos de confirmação: lançamento manual,
  importação, assistente) e o que precisa de computação.
- Os schemas com escrita (`ledger`, `imports`, `assistant`) não são expostos: o
  navegador não escreve direto em nada. O `pg_graphql` foi desligado para não abrir
  uma segunda porta de leitura.

## Consequências

- O módulo `api` vira duas coisas: o contrato de leitura (views `marts.*`,
  versionadas em migration) e a FastAPI de escrita.
- O `/demo` funciona mesmo com a API fora do ar.
- Mudança de formato de leitura é migration, não deploy da API.
- Toda regra de quem vê o quê precisa estar no RLS; não existe "filtro na API" para
  leitura.
