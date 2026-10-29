# Cauri: arquitetura

> Proposta aprovada em 29/10/2026, já com os ajustes do checkpoint de aprovação.
> Este arquivo é a fonte da verdade da arquitetura; mudou a decisão, muda aqui primeiro.

Portal de investimentos pessoal, modular, com acesso remoto, para poucos usuários
convidados. Também é peça de portfólio: o repositório é público e existe um modo
`/demo` aberto, sem login, com uma carteira fictícia.

## Princípios

- **Ledger é a fonte única de verdade.** Tudo que aparece na tela é derivado dele.
- **Dinheiro e quantidade em `numeric`/`Decimal` de ponta a ponta**, nunca float.
  O front só formata (pt-BR, `R$ 1.234,56`).
- **Nada de preço estimado.** Fonte falhou: vale o último preço válido, marcado
  como desatualizado.
- **Renda fixa mostra "valor bruto"** em todas as telas até o IR ser implementado.
- **Repositório público:** nenhum dado pessoal, e-mail ou carteira real em código,
  seeds, testes ou screenshots. Screenshots do README só a partir do `/demo`.
  Admin inicial e qualquer configuração pessoal entram por variável de ambiente.

## 1. Visão geral

```
Navegador · Cloudflare Pages (estático)
│
├── /demo (sem login, chave pública, sem sessão) ──┐
├── /app  (leitura com JWT) ───────────────────────┴──► Supabase
│                                                       ├ PostgREST: só as views marts.*
│                                                       ├ RLS: anon vê só o demo, membro só o próprio
│                                                       └ Auth: magic link + hook da allowlist
│
└── /app  (escrita com JWT) ──► API Python · FastAPI ──► Postgres (SET ROLE authenticated)
                                (VPS, Docker Compose atrás do Nginx)
                                importers, manual_entry, nl_assistant → ledger
                                engine.recalc, Anthropic (Haiku), transcrição (Groq)

GitHub Actions · cron 21h30 UTC seg a sex ──► jobs.daily (role cauri_ingest)
   brapi, BCB SGS, CoinGecko, Tesouro Transparente → raw → market → engine.snapshots
```

### Decisões estruturais

**a) Host da API Python: VPS própria.** A API roda na VPS que já hospeda outros
serviços, no padrão `/opt/cauri/` com Docker Compose (`restart: unless-stopped`),
Nginx como proxy reverso e Certbot para TLS. O Dockerfile é portável (imagem única,
config só por variável de ambiente, porta via `$PORT`), então migrar para Cloud Run
ou outro host de containers não exige reescrita.

**b) Leitura direto no Supabase, escrita pela API.** Os dashboards leem as views do
schema `marts` pelo PostgREST, com o RLS filtrando. A FastAPI recebe só escrita (os
fluxos de confirmação) e o que precisa de computação. Assim o `/demo` e as telas não
dependem da API estar no ar, e existe um único filtro de acesso: o RLS. O módulo
`api` é duas coisas: o contrato de leitura (views `marts.*`, versionadas em migration)
e a FastAPI de escrita.

## 2. Estrutura de pastas

```
cauri/
├── README.md                    # peça de portfólio (Fase 6)
├── docs/
│   ├── arquitetura.md           # este arquivo
│   ├── adr/                     # uma decisão técnica por arquivo
│   └── screenshots/             # gerados pelo Playwright, só do /demo
├── supabase/
│   ├── config.toml
│   ├── migrations/              # schemas, RLS, triggers, views
│   └── tests/                   # pgTAP: isolamento, RLS, invariantes do ledger
├── reference/                   # dados de referência versionados
│   ├── aliases.yaml             # petrobras→PETR, itau→ITUB, itausa→ITSA, bb→BBAS
│   ├── brokers.yaml
│   └── import-template/         # template da planilha genérica + exemplo
├── backend/                     # workspace uv, Python 3.13
│   ├── pyproject.toml           # ruff, mypy --strict, pytest, import-linter
│   ├── packages/                # cada um: src/<nome>/ + tests/
│   │   ├── core/                # Money, Qty, AssetClass, MovementType, calendário B3
│   │   ├── storage/             # pool, sessão com RLS (SET ROLE + claims), repositórios
│   │   ├── ledger/              # post/amend/void, validação, reconciliação
│   │   ├── engine/              # PM, posição, RF/CDI, TWR, snapshots, recalc
│   │   ├── importers/           # registry + adapters/ (generic, ...) + preview/commit
│   │   ├── manual_entry/        # formulário → rascunho de ledger, autocomplete
│   │   ├── nl_assistant/        # llm/ (Anthropic + fake), resolver, transcriber/
│   │   └── ingest_market/       # sources/ (brapi, bcb_sgs, coingecko, tesouro, cotahist)
│   └── apps/
│       ├── api/                 # FastAPI: rotas finas, JWT via JWKS, Dockerfile
│       └── jobs/                # CLI: daily, backfill, recalc, seed_demo, bootstrap_admin
├── deploy/
│   └── vps/                     # docker-compose.yml, exemplo de server block do Nginx
├── web/                         # React 19 + Vite + TS + Tailwind v4
│   ├── public/
│   │   ├── bg/                  # foto de fundo (webp/avif)
│   │   ├── _redirects           # fallback de SPA
│   │   └── _headers             # CSP e cache
│   ├── src/
│   │   ├── theme/               # tokens.ts (cores, blur, raios, sombras) + glass.css
│   │   ├── ui/                  # GlassCard, Pill, Segmented, KpiCard, Dock, TopBar, Ring
│   │   ├── features/            # home, portfolio, ledger, import, assistant, admin
│   │   ├── data/                # LiveSource (/app) e DemoSource (/demo, só leitura)
│   │   ├── lib/                 # formatação pt-BR, datas, helpers de motion
│   │   └── routes/              # /login, /app/*, /demo/*
│   └── e2e/                     # Playwright: screenshots desktop e celular por tela
├── .github/workflows/           # ci, deploy, daily-market, backfill
└── justfile                     # dev, test, db-reset, seed
```

Pacotes são criados na fase em que entram (importers na 4, nl_assistant na 5 etc.).
No front, o framer-motion hoje se chama Motion (`motion/react`), com a mesma API.
Dados no front via TanStack Query.

### Fronteiras entre módulos

Checadas no CI com import-linter, então não ficam só na convenção:

```
api ──► importers ────┐
    ├─► manual_entry ─┼──► ledger ──► storage ──► core
    ├─► nl_assistant ─┘
    └─► engine ─────────────────────► storage
jobs ─► ingest_market ──────────────► storage
     └► engine
```

- Nenhum módulo importa `api` nem `jobs`.
- importers, manual_entry e nl_assistant só chegam ao banco pelo `ledger`.
- `ingest_market` não sabe que o ledger existe.
- `engine` tem um núcleo puro (sem I/O) e uma camada fina que lê e grava no banco.

```python
ledger.check(user, drafts) -> list[DraftCheck]          # erros, venda > posição, possíveis duplicados
ledger.post(user, drafts, origin) -> list[MovementId]   # atômico e idempotente
ledger.amend(user, id, patch, reason) / ledger.void(user, id, reason)
importers.parse(files) -> ImportPreview ; importers.commit(user, batch_id, decisions)
nl_assistant.interpret(user, text, today) -> Interpretation   # itens resolvidos + perguntas
engine.recalc(user, from_date) ; engine.run_daily(day)
ingest_market.run(day) -> RunReport ; ingest_market.backfill(assets, since)
```

## 3. Schema do banco

Cada módulo é dono do seu schema. As camadas vão de raw (como chegou) a curated
(limpo) e marts (pronto pra tela).

| schema | dono | camada | escopo |
|---|---|---|---|
| raw | ingest_market | raw | compartilhado |
| market | ingest_market | curated | compartilhado |
| ledger | ledger | curated | por usuário |
| imports | importers | raw + curated | por usuário |
| assistant | nl_assistant | raw + curated | por usuário |
| engine | engine | marts (materializado) | por usuário |
| marts | api | marts (views) | por usuário, via RLS |
| app | auth/admin | n/a | misto |
| ops | jobs | log | admin |

```sql
-- app
app.allowlist      (email text pk sempre minúsculo, role 'admin'|'user', added_by, added_at, note)
app.profiles       (user_id pk → auth.users, display_name, created_at)
app.settings       (key pk, value jsonb)                                 -- demo_user_id etc.
app.goals          (user_id pk, target_amount, target_date)              -- anel "Meta"
app.notifications  (id, user_id, kind, payload jsonb, created_at, read_at)

-- market (compartilhado)
market.issuers        (code pk, name)               -- 'PETR', 'ITUB', 'ITSA': raiz de 4 letras da B3
market.assets         (id pk, ticker unique, class, issuer_code → issuers, name,
                       provider_ids jsonb, maturity_date, active)
market.asset_aliases  (alias_norm pk, issuer_code | asset_id)
market.brokers        (id pk, name, kind 'corretora'|'banco'|'exchange')
market.prices_daily   (asset_id, price_date, currency 'BRL'|'USD', close numeric(28,10),
                       source, run_id;  pk (asset_id, price_date, currency))
market.indicators     (series 'CDI'|'SELIC_META'|'SELIC_EFETIVA'|'IPCA', ref_date, value, unit, run_id)
market.calendar       (day pk, b3_open bool)

-- raw
raw.market_payloads   (id, run_id, source, request jsonb sem token, http_status, payload jsonb,
                       sha256, fetched_at)

-- ledger (por usuário, fonte única de verdade)
ledger.fi_instruments (id, user_id, kind 'CDB'|'LCI'|'LCA', issuer_name, indexer 'CDI',
                       rate_pct, maturity_date, broker_id, label)
ledger.movements (
  id uuid pk, user_id → auth.users, trade_date,
  asset_id → market.assets | instrument_id → ledger.fi_instruments,   -- exatamente um
  asset_class, type compra|venda|aporte|resgate|provento|desdobramento|grupamento|bonificacao,
  income_kind dividendo|jcp|rendimento|juros,                          -- só provento
  quantity numeric(28,10), unit_price numeric(28,10), fees, amount, factor,
  broker_id, origin 'import'|'manual'|'chat', origin_ref uuid, origin_label,  -- 'Planilha XP'
  idempotency_key, unique (user_id, idempotency_key),
  orig_currency, orig_value, fx_rate, fx_date, fx_source 'ptax'|'fechamento',  -- outra moeda
  fee_asset, fee_quantity,                                             -- taxa como foi paga
  opening_balance,                       -- compra marcada como saldo inicial
  version, created_at, updated_at, voided_at, voided_by, void_reason)
ledger.movement_history (movement_id, version, op, before jsonb, after jsonb, actor, reason, at)

-- imports (por usuário; o arquivo e o nome dele nunca são guardados)
imports.batches  (id, user_id, status 'preview'|'committed'|'discarded', warnings jsonb,
                  created_at, finished_at)
imports.files    (id, batch_id, user_id, position, label, sha256, size_bytes, adapter,
                  adapter_version)                       -- label: "B3 · Negociação, 01/2026 a 06/2026"
imports.rows     (id, file_id, user_id, position, line_numbers int[], raw jsonb, draft jsonb,
                  idempotency_key, status 'ok'|'error'|'already_imported'|'possible_duplicate'
                  |'ignored', messages jsonb, match_movement_ids uuid[],
                  decision 'import'|'keep_existing'|'replace'|'import_new',
                  movement_id → ledger.movements)
imports.profiles (id, user_id, name, mapping jsonb, options jsonb, created_at, updated_at,
                  last_used_at)          -- só nomes de colunas e opções, nunca conteúdo
-- batches também guarda suggestions (saldos iniciais sugeridos); rows guarda transfer
-- (depósito ou saque lido do arquivo, que explica saldo que falta)

-- assistant (por usuário)
assistant.conversations  (id, user_id, title, created_at, updated_at)
assistant.messages       (id, conversation_id, user_id, role, content, input_mode 'texto'|'voz',
                          llm_model, llm_output jsonb, created_at)   -- llm_output: só a frase entendida
assistant.proposals      (id, message_id, user_id, status 'pending'|'confirmed'|'cancelled',
                          items jsonb, suggestions jsonb, created_at, finished_at)
                          -- itens do cartão em jsonb: poucos, e mudam juntos a cada resposta

-- engine (por usuário)
engine.position_snapshots  (user_id, snap_date, asset_id|instrument_id, broker_id, quantity,
                            avg_cost, cost_basis, price, price_date,
                            price_status 'ok'|'stale'|'missing', market_value, realized_pnl, income_cum)
engine.portfolio_snapshots (user_id, snap_date, market_value, net_flows, quota_value,
                            cdi_index, ipca_index, stale_count, computed_at)
engine.dirty_ranges        (user_id pk, from_date)

-- marts: views com security_invoker (o RLS das tabelas continua valendo)
marts.me, positions_current, allocation, monthly_evolution, kpis(period), agenda,
recent_movements, movements

-- ops
ops.job_runs      (id, job, trigger 'cron'|'manual', started_at, finished_at, status, git_sha)
ops.source_status (run_id, source, status 'ok'|'partial'|'failed'|'quota_exceeded',
                   requested, succeeded, failed, error_sample, duration_ms)
ops.quota_usage   (source, month, used)
```

As tabelas de `imports`, `assistant` e as views `marts` entram nas fases em que são
usadas; o desenho acima é o alvo.

### Regras que valem destacar

- **As regras do ledger também ficam no banco:**
  - DELETE é revogado e bloqueado por trigger. Remover é preencher `voided_at`.
  - Todo insert e update gera auditoria por trigger em `movement_history`.
  - Uma constraint trigger diferida garante que a posição nunca fica negativa em
    nenhum ponto da linha do tempo. Isso pega venda retroativa e também a remoção de
    uma compra antiga que deixaria uma venda posterior descoberta.
  - O Python valida antes para dar um erro amigável. O banco é a última linha.
- **Recálculo retroativo:** um trigger no ledger grava em `engine.dirty_ranges` a menor
  data afetada. A API recalcula logo depois do commit, e o job da noite pega o que
  tiver sobrado.
- **Empresas nunca se misturam.** Emissor é a raiz de 4 letras do ticker. O apelido
  aponta para o emissor, com comparação exata depois de normalizar (sem acento,
  minúsculas) e sem fuzzy silencioso. "itau" e "itausa" caem em raízes diferentes.
- **O LLM não vê a carteira.** Ele só extrai `{tipo, ativo como falado, qtd, preço?,
  data?}`. A resolução para ticker e a regra de ambiguidade são código Python
  determinístico, melhor para privacidade e para os testes.
- **Idempotência da importação:** cada linha vira a chave `imp:<fonte>:<hash>`, com o hash
  do conteúdo normalizado (data, tipo, ativo, corretora, números) e da ordem de ocorrência
  entre linhas iguais do mesmo arquivo.
  - Reenviar o arquivo não duplica nada.
  - Um export com período sobreposto também não.
  - Duas compras idênticas no mesmo dia continuam sendo duas.
- **Reconciliação:** cruza (ativo, data, tipo, quantidade, ou valor, ou fator) com o que
  veio de outra fonte (manual, chat ou outra importação: a B3 e a planilha própria são
  fontes diferentes) e oferece "manter a existente" (padrão), "substituir pela planilha"
  ou "importar como nova". Substituir remove a antiga, com motivo no histórico, na mesma
  transação em que a nova entra; por isso trocar uma venda manual pela mesma venda da B3
  não acusa venda descoberta.
- **Rentabilidade pelo método de cotas (TWR diário)**, para aporte não distorcer o
  percentual. CDI e IPCA viram índices acumulados no mesmo período. O IPCA entra mês a
  mês, só com meses já publicados.
- **Renda fixa:**
  - cada aporte rende desde a própria data, com fator diário `1 + CDI_d × %contratado`
    e a convenção de arredondamento da B3;
  - resgate consome por FIFO;
  - **valor bruto**, sempre rotulado assim na tela (o IR fica como melhoria futura);
  - o CDI do dia que ainda não saiu não é estimado: acumula até o último publicado, e
    o snapshot informa até quando.
- **Preço médio** pela regra da Receita: custo médio ponderado incluindo taxas; venda
  não altera o PM; desdobramento, grupamento e bonificação ajustam quantidade e PM.
- **Fonte falhou:** o snapshot fica com o último preço válido, marcado como `stale` e
  com `price_date`. A tela mostra "sem atualização desde dd/mm".

## 4. Acesso, RLS e isolamento do /demo

1. O admin adiciona o e-mail na tela de Admin.
2. A pessoa pede o magic link. Um **Before User Created hook** do Supabase recusa
   qualquer e-mail fora da allowlist. A tela responde sempre a mesma mensagem genérica,
   para não revelar quem está na lista.
3. Remover da allowlist corta o acesso na hora, porque toda policy checa
   `app.is_member()` além do `user_id`.
4. O admin inicial é criado por `jobs bootstrap_admin`, que lê `ADMIN_EMAIL` do
   ambiente. Nenhum e-mail pessoal vai para o código.

| | anon (/demo) | membro | admin | cauri_ingest (job) |
|---|---|---|---|---|
| tabelas por usuário | só leitura do demo | só as próprias | só as próprias | snapshots: escrita; ledger: leitura |
| market | só ativos da carteira demo + indicadores | leitura | leitura | escrita |
| app.allowlist | não | não | tudo | não |
| ops | não | não | leitura | escrita |

**Como o demo fica separado dos dados reais:**
- O usuário demo não está na allowlist e tem e-mail inválido, então nunca loga.
- O `/demo` usa um cliente Supabase próprio, sem sessão. Mesmo com alguém logado no
  `/app` no mesmo navegador, ele não leva o JWT.
- O anon não lê a lista de ativos rastreados. Ela vem das carteiras reais, então
  revelaria o que os usuários têm.
- No front, o `DemoSource` não tem nenhum método de escrita, e isso é checado em tempo
  de compilação.
- Importar e Assistente no `/demo` são vitrine estática (uma pré-visualização de
  exemplo e uma conversa gravada), sem nenhuma chamada ao backend.

**A API escreve sem service role.** Ela conecta como `cauri_api` e roda cada request
numa transação com `SET LOCAL ROLE authenticated` + as claims do JWT, então o RLS vale
também no backend. Os schemas com escrita (`ledger`, `imports`, `assistant`) não são
expostos no PostgREST, e o pg_graphql fica desligado.

## 5. Fluxo de deploy

```
PR ──────────► ci.yml
               ruff + mypy --strict + pytest + import-linter
               tsc + vitest + vite build
               supabase start no runner → migrations → pgTAP (RLS e isolamento)

merge main ──► deploy.yml (environment "production", aprovação manual)
               1. supabase db push
               2. API: docker build → push ghcr.io/<owner>/cauri-api:<sha>
                  → SSH na VPS → cd /opt/cauri && docker compose pull && docker compose up -d
               3. web: Cloudflare Pages builda web/ pela integração com o Git

cron ────────► daily-market.yml "30 21 * * 1-5"
               ingest_market.run → engine (dirty + snapshot do dia) → ops

manual ──────► backfill.yml: histórico de preços, seed do demo, recalc geral
```

**Na VPS (`/opt/cauri/`):**
- `docker-compose.yml` com o serviço `api` (`restart: unless-stopped`), ouvindo só em
  `127.0.0.1`; o Nginx faz o proxy de `api.<domínio>` e o Certbot cuida do TLS.
- `.env` com `chmod 600`, fora do git, lido pelo compose.
- A conexão com o Postgres do Supabase vai pelo pooler (Supavisor), que aceita IPv4.
  Em modo transação, o psycopg roda sem prepared statements e cada request usa
  `SET LOCAL` dentro da própria transação.
- A imagem no GHCR não carrega segredo nenhum; pode ser pública como o repo.

**Onde fica cada segredo:**
- **Cloudflare Pages:** só a URL do Supabase, a chave publishable (pública por design,
  quem protege é o RLS) e a URL da API. O `_headers` define uma CSP que libera só
  Supabase e API.
- **VPS (`/opt/cauri/.env`):** a connection string do `cauri_api`, `ANTHROPIC_API_KEY`,
  `GROQ_API_KEY`, origens liberadas no CORS.
- **GitHub secrets:** a connection string do `cauri_ingest`, `BRAPI_API_KEY`,
  `COINGECKO_API_KEY`, o token e a senha do banco para migration, `VPS_HOST`,
  `VPS_USER` e `VPS_SSH_KEY` (chave dedicada ao deploy).

**Ambiente local:** `supabase start` (Docker; OrbStack no Mac, Docker Desktop no
Windows), `uvicorn` e `vite`, tudo chamado pelo `justfile`. Não tem staging: as
migrations rodam no CI contra o Supabase local antes do push.

**Limites dos planos gratuitos, já tratados:**
- O GitHub desliga o cron de repo público depois de 60 dias sem atividade. Um passo de
  keepalive reativa o workflow pela API, sem precisar de commit.
- O Supabase free pausa o projeto depois de 7 dias parado. O job diário mantém ele ativo.
- O banco tem 500 MB. O raw guarda o JSON das APIs. Dos arquivos grandes (CSV do
  Tesouro, COTAHIST) guarda só as linhas dos ativos rastreados + o hash. Retenção de
  12 meses.

## 6. Fontes de dados e fases de entrega

### O que foi conferido ao vivo (29/10/2026) e mudou o plano

- **A série SGS 1178 não é a Selic meta.** É a Selic efetiva anualizada (13,65% na
  data). A meta do Copom é a **432** (13,75%). Gravamos as duas.
- **O brapi gratuito não cobre Tesouro** (só no Pro), tem **histórico de só 3 meses** e
  **não traz dividendos**. As 15 mil requisições/mês, com 1 ativo por chamada, dão
  folga para uns 600 tickers por dia útil.
- **O fechamento às 18h30 fica no limite de novembro a março.** A B3 acompanha o
  horário de verão americano (Ofício Circular 005/2026-PRE): com ele (2º domingo de
  março ao 1º domingo de novembro), a negociação contínua vai até 16h55 e o call de
  fechamento até 17h; sem ele, até 17h55 e 18h. A brapi gratuita tem uns 30 min de
  atraso, então de novembro a março o fechamento pode não ter chegado às 18h30. O job
  só aceita como fechamento a cotação do dia posterior ao início do call; antes disso o
  ativo fica pendente, e a segunda passada às 19h30 completa só o que faltou. Em 2026 o
  horário de verão americano termina em 01/11; o primeiro pregão com fechamento às 18h
  é 03/11 (02/11 é Finados). *Na proposta original isso estava invertido; corrigido na
  Fase 2.*

### Fontes por uso

| uso | fonte | observação |
|---|---|---|
| fechamento diário de ações e FIIs | brapi.dev | só isso; token em `BRAPI_API_KEY`; cota mensal controlada em `ops.quota_usage`, sem retry em erro de limite |
| histórico de ações e FIIs (backfill, seed do demo) | COTAHIST da B3 | oficial e grátis; também é a lista oficial de tickers do autocomplete |
| Tesouro Direto (diário e histórico) | CSV do Tesouro Transparente | oficial e grátis; sai por volta das 10h do dia seguinte, então o job das 18h30 grava o PU de D-1, marcado como D-1 |
| CDI, Selic meta, Selic efetiva, IPCA | API SGS do Banco Central | séries 12, 432, 1178 e 433 |
| cripto (BRL e USD) | CoinGecko Demo | vários ativos por chamada, 365 dias de histórico; crédito "Data provided by CoinGecko" no rodapé |
| proventos futuros | sem fonte grátis | no v1 a Agenda mostra vencimentos de renda fixa e proventos já lançados com data futura |
| transcrição de voz | Whisper via Groq | atrás de uma interface `Transcriber`; sem `GROQ_API_KEY`, o front cai para a Web Speech API do navegador |
| interpretação de texto | API da Anthropic | modelo Haiku com saída estruturada |

### Fases de entrega

Cada fase termina com checkpoint: testes verdes, resumo do que entrou e, a partir da
Fase 3, screenshots de cada tela em desktop e celular.

1. **Fundação (entregue):** schema, RLS, auth com allowlist, ledger, lançamento manual
   (backend: módulo `manual_entry` + endpoints na API; a tela vem com Lançamentos na
   Fase 3), engine com testes e seed do demo (usuário + ledger fictício de 12 meses,
   várias corretoras). Para o demo nascer com preço real, o backfill histórico
   (COTAHIST, Tesouro Transparente, CoinGecko e SGS) e a sincronização de ativos
   foram antecipados para esta fase. O engine já calcula os snapshots em memória; a
   gravação deles é da Fase 2.
2. **Mercado (entregue):** job diário no GitHub Actions (brapi para o fechamento de ações
   e FIIs, CoinGecko, Tesouro Transparente, SGS) com log por fonte e controle de cota,
   gravação dos snapshots (inclusive os do demo, por classe e por corretora), recálculo
   pela API depois de cada escrita no ledger e processamento de `engine.dirty_ranges`
   pelo job.
3. **Frontend (entregue):** 3a, tema de vidro, componentes e Início no `/demo`; 3b,
   Carteira, Lançamentos (com o lançamento manual, edição e remoção), Admin e `/app` com
   login por magic link.
4. **Importação:** importers (B3 Negociação e Movimentação, template genérico e o
   export da exchange de cripto; corretoras individuais só se a B3 não cobrir algo), tela
   Importar, reconciliação entre origens, vitrine estática no `/demo`.
5. **Assistente (entregue):** `nl_assistant`, tela Assistente com texto e voz, vitrine estática no
   `/demo`.
6. **Deploy final:** Cloudflare Pages, Supabase em produção, API na VPS via GitHub
   Actions, README de portfólio.

### Job diário

Dois agendamentos em UTC no `.github/workflows/daily-market.yml`, seg a sex: `30 21`
(18h30 em Brasília) e `30 22` (19h30). Brasília é UTC-3 o ano todo, então os horários
não mudam; o que muda é o fechamento da B3 (ver acima).

1. Monta a lista de ativos pela união das carteiras (inclusive a demo), sem repetir.
2. Busca o fechamento do dia em cada fonte, cada uma na sua transação, com o resultado
   em `ops.source_status` (`ok`, `partial`, `failed`, `quota_exceeded`, `skipped`).
   - brapi: um ativo por chamada, token só no header, cota mensal conferida antes de
     cada chamada (`ops.quota_usage`); limite atingido ou plano sem acesso param a fonte
     sem nova tentativa; rede e 5xx têm uma nova tentativa no máximo.
   - CoinGecko: todos os criptoativos numa chamada, BRL e USD. Cripto não tem
     fechamento: vale o preço no momento da coleta.
   - Tesouro: PU de D-1 (sai na manhã seguinte), marcado com a própria data.
   - SGS: últimos dias de CDI, Selic meta, Selic efetiva e IPCA.
3. Grava resposta crua (`raw.market_payloads`, sem token) e versão limpa
   (`market.prices_daily`, `market.indicators`).
4. Recalcula os snapshots de cada carteira a partir da menor data entre a marca do ledger
   e 7 dias atrás (para absorver dado que chega atrasado, como o PU de D-1).
5. Segunda passada: só chama a fonte para o que ainda não tem preço do dia.

Sem `CAURI_INGEST_DATABASE_URL` nos secrets (até a Fase 6), o agendamento roda e sai
sem erro. Um passo de keepalive reativa o workflow pela API em toda execução.

**Demo com ledger fictício e preço real:** tickers de verdade (PETR4, BTC) com uma
carteira inventada, e o patrimônio do demo se mexe todo dia com o mercado.

## 6b. Frontend

- **Tema num arquivo só:** `web/src/theme/tokens.ts` (cores, vidro, raios, sombras, movimento).
  `applyTheme()` escreve tudo como variáveis CSS `--cauri-*`; `glass.css` só dá nome a elas
  para o Tailwind e define o vidro. Trocar o visual é editar os tokens.
- **Fundo:** foto do chalé ao entardecer ([Jonathan Borba, Pexels](https://www.pexels.com/photo/living-room-in-wooden-luxury-modern-hut-with-view-on-mountains-19737857/),
  Pexels License, atribuição opcional, creditada no rodapé). AVIF e WebP em 1280, 1920 e
  2560 px, mais um placeholder borrado de ~180 bytes embutido no código
  (`scripts/optimize-bg.mjs`). Cada foto tem seu próprio véu no manifesto.
- **Contraste AA medido, não estimado:** `e2e/contrast.spec.ts` mede a razão WCAG de todo
  texto visível contra o fundo real atrás dele (foto, véu e vidro). Para passar no AA, o
  briefing foi ajustado (aprovado em 29/10/2026): véu de 72% no topo e 62% na base para o
  chalé (o céu claro fica no alto), vidro em 8% (o mínimo da faixa), textos secundários em
  branco 78% e rótulos em 70% (o briefing previa 60% e 50%), selos de variação com fundo
  escuro e iniciais escuras no avatar laranja.
- **Trava no CI:** o job "Interface" roda o contraste e a checagem de "nenhuma rolagem
  horizontal" no desktop e no celular, com o backend simulado pelas fixtures do demo
  (`e2e/fixtures`, regravadas por `scripts/capture-fixtures.mjs`).
- **Período padrão do Início:** "Tudo" no `/demo` (carteira de 12 meses) e "Ano" no `/app`.
- **Linha "CDI" do gráfico:** o mesmo dinheiro, com as mesmas entradas e saídas nas mesmas
  datas, rendendo 100% do CDI. Calculada pelo engine (`cdi_equivalent`), não no front.
- **Demo só de leitura pelo tipo:** `DemoSource` não tem método de escrita; o cliente
  Supabase do demo não guarda sessão nem manda JWT.
- **Fonte:** Inter (algarismos tabulares de verdade). Bundle dividido por biblioteca, telas
  carregadas sob demanda.

### /app (Fase 3b)

- **Login:** magic link com PKCE (`/login`). Quem não está na allowlist é recusado pelo hook
  do Supabase Auth; a tela mostra sempre a mesma mensagem ("se o seu e-mail estiver na lista
  de convidados..."), sem revelar nada. Sessão válida fora da allowlist cai numa tela de
  "acesso restrito".
- **Um só cliente de sessão** para `/login` e `/app`; o `/demo` fica fora dele e nunca lê
  nem cria sessão.
- **Escrita só pela API**, com o fluxo de confirmação: "Conferir" chama `/v1/movements/check`
  (erros e duplicados prováveis), "Confirmar" grava. A chave de idempotência nasce com o
  formulário, então clique duplo não duplica. Edição pede motivo opcional e remoção pede
  motivo obrigatório; os dois vão para o histórico de auditoria.
- **Admin** (só para admin, e a API e o RLS recusam os outros): allowlist (convidar, trocar
  papel, remover) e o log dos jobs por fonte (`marts.job_runs`, `marts.job_sources`).
- **Período padrão do Início no /app:** "Ano".
- **Testes de interface:** a bateria simulada (9 telas, desktop e celular, contraste AA e
  sem rolagem horizontal) roda no CI. A bateria ao vivo (`CAURI_E2E_LIVE=1`) faz o fluxo
  real com Supabase, API e Mailpit locais: login pelo magic link, lançamento gravado pela
  API, admin e a allowlist barrando quem não foi convidado.

### Importar (Fase 4)

- **Vários arquivos por envio**, `.xlsx` ou `.csv`, até 10 de 5 MB. O formato é detectado
  pelo cabeçalho (B3 Negociação, B3 Movimentação ou template do Cauri).
- **Pré-visualização antes de gravar:** cada linha aparece como pronta, possível duplicada,
  já importada, com erro ou ignorada, sempre com o motivo. Duplicados têm a decisão na
  própria linha. Nada entra no ledger antes de "Importar N".
- **O arquivo nunca é guardado**, nem o nome dele: o lote guarda um rótulo gerado, o hash e
  o tamanho. O leitor só carrega as colunas que o adaptador declara (CPF, nome e qualquer
  outra coluna nem entram na memória do resto do sistema); texto livre com cara de CPF é
  mascarado; e uma constraint no banco recusa CPF formatado no `raw`.
- **Templates para baixar** na própria tela (bolsa e cripto, `.xlsx` e `.csv`), gerados pelo
  mesmo script das fixtures (`backend/packages/importers/tests/fixtures/build_fixtures.py`).
- **Formato desconhecido:** a pré-visualização mostra as colunas do arquivo e o usuário diz
  qual é cada campo (data, tipo, ativo, quantidade, preço, valor, taxa, moeda...), com
  corretora fixa, formato de data e de número. Isso vira um perfil salvo por usuário (RLS),
  reconhecido pelo cabeçalho nas próximas vezes. Serve para bolsa e para cripto.
- **No /demo**, uma pré-visualização de exemplo com dados inventados, sem chamada ao backend.

## 7. Decisões confirmadas

| tema | decisão |
|---|---|
| estrutura, schema, deploy | aprovados |
| host da API | VPS própria com Docker Compose, Nginx e Certbot em `/opt/cauri/`; deploy por SSH a partir do GitHub Actions; imagem no GHCR; Dockerfile portável |
| eventos corporativos | desdobramento, grupamento e bonificação no enum desde a Fase 1 |
| ambiente local | `supabase start` com banco local |
| cripto | CoinGecko Demo com atribuição no rodapé |
| voz | Whisper via Groq atrás de interface; Web Speech API como fallback sem chave |
| foto de fundo | chalé ao entardecer (Pexels), escolhida entre 3 opções na Fase 3 |
| template genérico | rascunho com as colunas abaixo; exemplos das corretoras na Fase 4 |
| Importar e Assistente no /demo | vitrine estática, sem chamadas ao backend |
| backfill | COTAHIST (B3) e Tesouro Transparente; brapi só no fechamento diário |
| renda fixa | rótulo "valor bruto" em todas as telas até o IR |
| repo público | nada pessoal em código, seeds, testes ou screenshots |

### Ajustes feitos durante a Fase 1

- **E-mail da allowlist em `text` minúsculo, sem `citext`.** Com `search_path` vazio nas
  funções security definer, o operador `=` do citext não era encontrado e a comparação
  virava sensível a maiúsculas. Normalizar para minúsculo é mais simples e explícito.
- **Erro `CA007`** para a tentativa de remover o último admin (os outros códigos `CA0xx`
  são do ledger).
- **Backfill antecipado** (ver Fase 1 acima). A brapi continua só no fechamento diário.
- **Chave de idempotência do demo com identificador da geração.** Depois de um reset, as
  chaves das movimentações anuladas continuam ocupadas (o ledger nunca apaga), então cada
  geração do demo usa chaves próprias.
- **CoinGecko com no máximo duas novas tentativas** em caso de limite por minuto (429),
  respeitando o `Retry-After`. Nunca insiste indefinidamente.
- **Rentabilidade por classe e por corretora** já sai do engine (uma cota por classe e
  por corretora). Na Fase 2 ganhou a tabela `engine.bucket_snapshots`.

### Ajustes feitos durante a Fase 2

- **Horário da B3 corrigido** (ver "O que foi conferido ao vivo" acima).
- **Snapshots vão até o último pregão com fechamento disponível** (fim do call + 30 min).
  Durante o pregão, o dia de hoje ainda não tem snapshot; movimentação lançada hoje
  aparece na lista na hora e no gráfico depois do fechamento.
- **Recálculo pela API em transação separada**, depois do commit da escrita: se falhar, a
  movimentação continua gravada, a marca em `engine.dirty_ranges` fica e o job da noite
  completa. A resposta do `POST /v1/movements` diz se os snapshots foram atualizados.

### Ajustes feitos durante a Fase 4

- **B3, regras de leitura** (layout dos exports públicos da Área do Investidor):
  - Negociação: só mercado à vista e fracionário (`PETR4F` vira `PETR4`). Opções, termo e
    futuros ficam como ignorados. O export não traz corretagem nem emolumentos, então as
    compras entram sem taxas (o envio avisa).
  - Movimentação: "Transferência - Liquidação" é reflexo de uma negociação e é ignorada,
    nunca vira movimento duplicado. Dividendo, JCP, Rendimento e Juros viram proventos;
    compra, venda, vencimento e resgate do Tesouro viram compra e venda do título.
  - Eventos (desdobro, grupamento, bonificação) chegam como quantidade creditada por
    corretora: as linhas do mesmo evento são somadas e o fator sai da posição consolidada
    na véspera (ledger + linhas anteriores do envio). A pré-visualização mostra a conta.
  - Ficam de fora, com o motivo na linha: fração e leilão de fração (centavos), taxa de
    custódia do Tesouro (valor bruto), empréstimo de ações, transferência de custódia entre
    corretoras (a posição total não muda; a visão por corretora pode ficar defasada) e
    amortização ou restituição de capital (o preço médio ainda não é ajustado).
  - Pedem lançamento manual, como erro explicado: subscrição exercida, incorporação e
    "Atualização". Tipo desconhecido também vira erro, nunca some calado.
- **Duplicado provável começa como "manter a existente"** e, na pré-visualização, não soma
  na simulação da linha do tempo (senão uma venda repetida apareceria como venda
  descoberta). Se o usuário escolher "importar como nova", a gravação confere de novo.
- **Mesma operação em dois arquivos de fontes diferentes no mesmo envio** (B3 e planilha
  própria) vira erro na segunda: importe em envios separados para escolher qual manter.
  Da mesma fonte (exports sobrepostos), a repetida é ignorada.
- **Se a carteira mudou entre a pré-visualização e a gravação**, a gravação é recusada
  inteira, com a linha e o motivo (tudo ou nada).
- **Template ganhou a coluna opcional `tipo_provento`** (padrão: dividendo para ação,
  rendimento para FII, juros para Tesouro e renda fixa).

### Cripto e perfis de importação (Fase 4, etapa 1c)

- **PTAX:** a de venda é a série SGS **1** (a série 10813 é a de compra; conferido na API do
  BCB, a 1 vem sempre maior). Entra em `market.indicators` como `PTAX_VENDA`, pelo job
  diário e pelo histórico.
- **Conversão para reais:** dólar e stablecoins (USDT, USDC, FDUSD...) pela PTAX de venda
  do dia da operação; outra cripto usada como moeda (par ETH/BTC, taxa em BNB) pelo
  fechamento do dia em reais. Sem cotação no dia (fim de semana, feriado, PTAX de hoje
  ainda não publicada), vale a última anterior, até 10 dias, e a linha diz qual data foi
  usada. O movimento guarda moeda, valor original, cotação, data e fonte.
- **Cada negociação mexe nos dois saldos.** Comprar BTC com USDT vira compra de BTC e venda
  de USDT; a taxa paga em BNB vira custo (em reais, somado à compra) e venda daquele BNB.
  Taxa na própria moeda comprada sai da quantidade recebida e entra como custo. Real e
  dólar não são posição, então pagar com eles não gera contrapartida.
- **Recompensas de Earn e staking** entram como provento pelo valor do dia e, junto, a
  quantidade recebida entra como compra pelo mesmo valor (reinvestida). Assim o rendimento
  aparece na rentabilidade sem distorcer o aporte, e o saldo da moeda bate com a exchange.
  Recompensa de menos de 1 centavo não vira provento, só a quantidade entra.
- **Binance:** trades (Spot, layout atual e antigo), Convert, depósitos e saques, e o extrato
  de transações. Do extrato vêm as recompensas; compras, vendas e conversões que também
  aparecem nele são ignoradas, porque vêm dos exports de trades e de Convert. Depósito e
  saque de cripto é transferência de custódia (backlog); em reais, é dinheiro em conta.
  P2P e Auto-Invest pedem lançamento manual. Horário em UTC vira o dia em Brasília.
  `User_ID`, endereço de carteira, TXID e observações nunca são lidos.
- **Perfis:** guardam só os nomes das colunas e as opções. O tipo de operação é lido por um
  vocabulário fixo (compra, buy, C; venda, sell, V; dividendo, rendimento, JCP; recompensa,
  staking), então nenhum valor do arquivo precisa ser guardado. O perfil reconhece o arquivo
  quando todas as colunas mapeadas estão no cabeçalho. Cada perfil é uma fonte própria para
  a reconciliação.
- **Teste de contraste:** a única exceção de visibilidade é texto escondido atrás de uma
  barra fixa (barra de ação da importação, dock, barra do topo), documentada no teste.

### Saldo inicial (fechamento da Fase 4)

- **Saldo inicial é uma compra marcada** (`opening_balance`): posição que já existia antes
  do histórico, com data, quantidade e custo médio informados pelo usuário. O "aporte" do
  Cauri é o tipo da renda fixa, então a marca vai na compra. O custo informado vale para o
  preço médio; para a rentabilidade, o engine conta a entrada pelo valor de mercado do dia,
  senão um custo antigo baixo viraria "rendimento" no dia em que o saldo entra.
- **Venda descoberta na importação vira oferta de saldo inicial.** A pré-visualização calcula,
  por ativo, quanto falta e desde quando (simulando todas as vendas do envio, não só a
  primeira) e sugere o saldo: na data do depósito que explica o saldo, quando há um no envio,
  ou na véspera da primeira venda descoberta. O custo médio vem preenchido com o fechamento do
  dia (PTAX de venda para stablecoins), marcado como sugestão. Incluir o saldo põe uma linha
  "Saldos iniciais" no lote e confere tudo de novo pelos rascunhos guardados, sem reenviar os
  arquivos; ele só entra no ledger junto com o resto, ao confirmar.
- **Depósito de cripto continua sem mexer na posição**, mas quando ele explica um saldo que
  falta, a linha do depósito avisa e a sugestão usa a data e a quantidade dele.
- **P2P da Binance** (compra e venda de cripto com real, a entrada mais comum de USDT no
  Brasil) virou adaptador. O P2P que aparece no extrato é ignorado, porque vem desse export.
  O apelido da contraparte e o número da ordem nunca são lidos.
- **Saldo inicial também no lançamento manual** (tipo "Saldo inicial") e nos templates
  (`saldo_inicial` no de bolsa, `saldo inicial` no de cripto e nos perfis).

### Assistente (Fase 5)

- **O LLM só extrai a frase.** Haiku (`claude-haiku-5-5`, configurável) com saída
  estruturada por ferramenta obrigatória, devolvendo para cada operação {tipo, ativo como
  falado, quantidade, preço, moeda, data}, com números como texto decimal (nunca float). O
  pedido leva só a frase e a data de hoje: nada da carteira. Uma nova tentativa em
  sobrecarga, nunca mais que isso.
- **Resolução em Python determinístico:** ticker escrito vale direto; apelido aponta para
  um emissor ou um ativo ("itau" é ITUB e "itausa" é ITSA, nunca se misturam); emissor com
  mais de um ticker usa o único que o usuário tem, e pergunta se ele tem os dois ou nenhum.
  Empresa com um ticker só não pergunta (não há ambiguidade). Tesouro pelo nome do título.
- **Campos que faltam:** data vira hoje (o cartão avisa); preço vira o fechamento mais recente,
  marcado como sugestão; corretora vira a única onde o ativo está, ou a mais recente da
  classe, editável no cartão.
- **Moeda estrangeira e cripto como na importação:** "a 120 mil dólares" converte pela PTAX de
  venda do dia; pagar com USDT (ou outra cripto) gera a contrapartida no saldo dela.
- **O cartão usa o mesmo `ledger.check`** do lançamento manual e da importação: erros,
  duplicados prováveis (agrupados numa linha por origem e data) e venda descoberta, que vira
  a mesma oferta de saldo inicial, dentro do cartão. Responder, editar, remover item ou
  incluir saldo recalcula o cartão inteiro; "Confirmar" grava tudo ou nada, com origem "Chat"
  e a mensagem como referência. Pendência (pergunta ou erro) impede confirmar.
- **Voz:** o navegador grava e a API transcreve pelo Whisper da Groq; sem `GROQ_API_KEY`, o
  front usa a Web Speech API do navegador. O texto volta para o campo e o usuário revisa antes
  de enviar. O áudio não é guardado.
- **Sem chave da Anthropic**, o assistente fica indisponível em produção. Em desenvolvimento e
  nos testes ao vivo, `CAURI_ASSISTANT_EXTRACTOR=regras` usa um extrator por regras que
  entende frases simples; a tela avisa que é o modo de desenvolvimento. O Haiku tem testes de
  formato com HTTP simulado e um teste opcional de verdade (`just test-llm`).
- **Tela:** conversas à esquerda, conversa ao centro com os cartões, resumo da carteira à
  direita (só na tela; nunca vai para a IA). No `/demo`, uma conversa gravada.
- **Conversão de moeda e saldo inicial sugerido foram para o `ledger`** (`ledger.fx`,
  `ledger.opening`): importação e assistente são canais irmãos e não importam um ao outro.

### Template de cripto

CSV ou XLSX, vírgula decimal, datas `dd/mm/aaaa`, uma linha por operação. Exemplo em
`reference/import-template/cauri-cripto.*` e no botão "Template cripto".

| coluna | obrigatória | exemplo | notas |
|---|---|---|---|
| `data` | sim | `12/03/2025` | |
| `tipo` | sim | `compra` | compra, venda, recompensa ou saldo inicial (preço = custo médio) |
| `ativo` | sim | `ETH` | código da cripto |
| `quantidade` | sim | `0,1` | |
| `preco` | compra e venda | `2.000,00` | preço unitário na moeda do preço |
| `moeda do preco` | não | `USDT` | BRL (padrão), USD ou uma cripto; cripto gera a contrapartida |
| `taxa` | não | `0,0001` | |
| `ativo da taxa` | não | `BNB` | sem ela, a taxa está na moeda do preço |
| `exchange` | sim | `Binance` | id ou nome cadastrado |
| `obs` | não | | texto livre |

### Template genérico de planilha

CSV ou XLSX, vírgula decimal, datas `dd/mm/aaaa`, uma linha por movimentação. O arquivo
de exemplo fica em `reference/import-template/` e no botão "Template" da tela Importar.

| coluna | obrigatória | exemplo | notas |
|---|---|---|---|
| `data` | sim | `15/03/2026` | data da operação |
| `tipo` | sim | `compra` | compra, venda, aporte, resgate, provento, desdobramento, grupamento, bonificacao, saldo_inicial (preço = custo médio) |
| `ativo` | sim | `PETR4` | ticker, nome do título do Tesouro ou rótulo do CDB/LCI |
| `classe` | sim | `acao` | acao, fii, tesouro, renda_fixa, cripto |
| `quantidade` | depende | `100` | compra e venda |
| `preco` | depende | `38,45` | preço unitário em compra e venda; na bonificação, o custo atribuído por ação nova |
| `fator` | depende | `2` | desdobramento e grupamento: ações novas por ação antiga (`2` = 1 vira 2, `0,1` = 10 viram 1); bonificação: ações novas por ação possuída (`0,1` = 10%) |
| `taxas` | não | `4,90` | corretagem e emolumentos |
| `valor` | depende | `5.000,00` | aporte, resgate, provento |
| `corretora` | sim | `Corretora X` | |
| `pct_cdi` | depende | `110` | renda fixa: % do CDI |
| `vencimento` | depende | `15/03/2028` | renda fixa |
| `emissor` | depende | `Banco Y` | renda fixa |
| `tipo_provento` | não | `rendimento` | dividendo, jcp, rendimento ou juros; sem ela, vale o padrão da classe |
| `obs` | não | | texto livre |
