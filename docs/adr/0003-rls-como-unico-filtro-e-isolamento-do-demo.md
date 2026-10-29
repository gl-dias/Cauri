# ADR 0003: RLS como único filtro de acesso e isolamento do demo

Status: aceita (29/10/2026)

## Contexto

Poucos usuários convidados dividem o mesmo banco, e existe um `/demo` público, sem
login, que não pode ter nenhum caminho até os dados reais. O repositório é público,
então a segurança não pode depender de nada escondido.

## Decisão

- Toda tabela tem RLS. Tabelas por usuário filtram por `user_id = auth.uid()` e
  por `app.is_member()`: quem sai da allowlist perde acesso na hora, mesmo com JWT
  válido.
- Cadastro: o hook `before_user_created` do Supabase Auth recusa qualquer e-mail
  fora de `app.allowlist`, com mensagem genérica.
- A API escreve sem service role: conecta como `cauri_api` (`noinherit`) e, em cada
  request, assume `authenticated` com as claims do JWT. O RLS vale no backend também.
- Jobs usam `cauri_ingest`, que escreve mercado e snapshots e não escreve no ledger.
- O usuário demo não está na allowlist e tem e-mail inválido; o role `anon` lê só
  as linhas dele. Do mercado, o anon vê só os ativos e corretoras que a carteira
  demo referencia (a lista completa de ativos rastreados revelaria carteiras reais),
  mais indicadores públicos do BCB.
- No front, o `/demo` usa um cliente Supabase próprio, sem sessão.

## Consequências

- Isolamento testado em pgTAP (`supabase/tests/rls_isolation.test.sql`) e na API.
- Senhas dos roles de serviço ficam fora das migrations (definidas à mão em produção).
- Toda tabela nova precisa nascer com RLS e policies para os quatro públicos: membro,
  admin, anon (demo) e job.
