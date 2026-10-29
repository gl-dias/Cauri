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
  version, created_at, updated_at, voided_at, voided_by, void_reason)
ledger.movement_history (movement_id, version, op, before jsonb, after jsonb, actor, reason, at)

-- imports (por usuário)
imports.batches  (id, user_id, status 'preview'|'committed'|'discarded', created_at, committed_at)
imports.files    (id, batch_id, user_id, filename, sha256, adapter, adapter_version, broker_id,
                  storage_path)
imports.rows     (id, file_id, user_id, row_number, raw jsonb, parsed jsonb, fingerprint,
                  status 'ok'|'error'|'already_imported'|'possible_duplicate', error,
                  match_movement_id, decision, movement_id → ledger.movements)

-- assistant (por usuário)
assistant.conversations  (id, user_id, title, created_at)
assistant.messages       (id, conversation_id, user_id, role, content, input_mode 'text'|'voice',
                          llm_model, llm_output jsonb, created_at)
assistant.proposals      (id, message_id, user_id, status 'pending'|'confirmed'|'cancelled')
assistant.proposal_items (id, proposal_id, user_id, resolved jsonb, pending_question,
                          price_is_suggested, movement_id → ledger.movements)

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
- **Idempotência da importação:** cada linha gera um fingerprint (adaptador + conteúdo
  normalizado + ordem de ocorrência no arquivo) que vira `idempotency_key`.
  - Reenviar o arquivo não duplica nada.
  - Um export com período sobreposto também não.
  - Duas compras idênticas no mesmo dia continuam sendo duas.
- **Reconciliação:** cruza (ativo, data, tipo, quantidade) com movimentos de outra
  origem e oferece "manter existente", "substituir pela planilha" ou "importar como nova".
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
- **O fechamento às 18h30 fica no limite.** O brapi gratuito tem uns 30 min de atraso,
  e no horário de verão americano o pregão fecha às 18h. O job confere o horário da
  cotação. Se ainda não for o fechamento, marca o ativo, e uma segunda passada às
  19h30 completa só o que faltou.

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
2. **Mercado:** job diário no GitHub Actions (brapi para o fechamento de ações e FIIs,
   CoinGecko, Tesouro Transparente, SGS) com log por fonte e controle de cota,
   gravação dos snapshots (inclusive os do demo), recálculo pela API depois de cada
   escrita no ledger e processamento de `engine.dirty_ranges` pelo job.
3. **Frontend:** tema de vidro, telas Início, Carteira, Lançamentos (com o lançamento
   manual) e Admin, `/app` e `/demo`. Três opções de foto de fundo livres de direitos
   para escolha.
4. **Importação:** importers (adaptador genérico + os das corretoras a partir dos
   exemplos), tela Importar, reconciliação entre origens, vitrine estática no `/demo`.
5. **Assistente:** `nl_assistant`, tela Assistente com texto e voz, vitrine estática no
   `/demo`.
6. **Deploy final:** Cloudflare Pages, Supabase em produção, API na VPS via GitHub
   Actions, README de portfólio.

**Demo com ledger fictício e preço real:** tickers de verdade (PETR4, BTC) com uma
carteira inventada, e o patrimônio do demo se mexe todo dia com o mercado.

## 7. Decisões confirmadas

| tema | decisão |
|---|---|
| estrutura, schema, deploy | aprovados |
| host da API | VPS própria com Docker Compose, Nginx e Certbot em `/opt/cauri/`; deploy por SSH a partir do GitHub Actions; imagem no GHCR; Dockerfile portável |
| eventos corporativos | desdobramento, grupamento e bonificação no enum desde a Fase 1 |
| ambiente local | `supabase start` com banco local |
| cripto | CoinGecko Demo com atribuição no rodapé |
| voz | Whisper via Groq atrás de interface; Web Speech API como fallback sem chave |
| foto de fundo | 3 opções livres de direitos na Fase 3 |
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
  por corretora). Onde gravar fica para a Fase 2 (provavelmente uma tabela
  `engine.bucket_snapshots`).

### Rascunho do template genérico de planilha

CSV ou XLSX, vírgula decimal, datas `dd/mm/aaaa`, uma linha por movimentação.

| coluna | obrigatória | exemplo | notas |
|---|---|---|---|
| `data` | sim | `15/03/2026` | data da operação |
| `tipo` | sim | `compra` | compra, venda, aporte, resgate, provento, desdobramento, grupamento, bonificacao |
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
| `obs` | não | | texto livre |
