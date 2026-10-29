# ADR 0002: invariantes do ledger garantidas pelo banco

Status: aceita (29/10/2026)

## Contexto

O ledger é a fonte única de verdade, e as movimentações chegam por três canais
(manual, planilha, assistente), além de scripts de manutenção. Se as regras
morassem só no Python, qualquer escrita por outro caminho (um script, o SQL Editor,
um bug num canal novo) poderia deixar a carteira inconsistente.

## Decisão

As regras ficam no Postgres (`supabase/migrations/20261029000400_ledger.sql`):

- DELETE e TRUNCATE são bloqueados por trigger, até para o dono das tabelas.
  Remover é preencher `voided_at` com motivo (soft delete).
- Todo insert e update gera uma linha em `ledger.movement_history` (antes, depois,
  quem, motivo), que é só de inserção.
- Uma constraint trigger diferida percorre a linha do tempo do ativo no commit e
  recusa qualquer estado com posição negativa (venda retroativa, compra removida,
  grupamento que descobre uma venda posterior). Um advisory lock por usuário
  serializa transações concorrentes.
- Formato de cada tipo, classe derivada do ativo e data futura (só provento) são
  constraints e triggers.
- Erros têm SQLSTATE próprio (`CA001` a `CA007`), traduzidos na API.

O Python (`cauri_ledger`) valida antes, com o mesmo cálculo de posição do engine,
para dar mensagem clara na tela; o banco é a última linha.

## Consequências

- Testes de banco em pgTAP (`supabase/tests/ledger_invariants.test.sql`) cobrem as
  regras independentemente do Python.
- Testes de integração não limpam dados: usuários novos por teste.
- A regra de posição existe em dois lugares (SQL e Python) e precisa ficar igual,
  inclusive a ordem dentro do dia (eventos, compras, vendas).
