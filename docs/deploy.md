# Produção

Roteiro para subir o Cauri do zero. O que precisa de conta ou de chave é feito por você
nos painéis; o resto é workflow do GitHub. Nenhuma chave passa pelo chat nem entra no repo.

```
Cloudflare Pages (<dominio-do-pages>) ──►  Supabase sa-east-1 (Postgres, Auth, PostgREST)
        │                                      ▲
        └──►  API na VPS (<api.seu-dominio>) ──┘   GitHub Actions: migrations, deploy da API,
              Nginx + Certbot, Docker                  job diário, monitoramento
```

## Valores para preencher

Fora as chaves e senhas (que só vão para os painéis e secrets), são estes:

| Valor | Exemplo | Onde entra |
|---|---|---|
| `<dominio-do-pages>` | `cauri-abc.pages.dev` ou `cauri.seu-dominio` | Auth do Supabase (1.5), CORS no `api.env` da VPS |
| `<ref>` do Supabase | `abcdefghijklmnopqrst` | `VITE_SUPABASE_URL` (Pages), `CAURI_SUPABASE_URL` e conexões |
| `<host-do-pooler>` | `aws-0-sa-east-1.pooler.supabase.com` | todas as conexões com o banco |
| `<api.seu-dominio>` | `api.exemplo.com.br` | Nginx e Certbot, `VITE_API_URL` (Pages), variável `API_URL` (GitHub) |
| `<dominio-do-email>` | `mail.exemplo.com.br` | Resend (2) e remetente do SMTP (1.7) |

**Atenção ao domínio do Pages:** `cauri.pages.dev` pertence a outro projeto (de terceiros),
então o Cloudflare dá ao nosso um endereço com sufixo. Use exatamente o que aparece no
painel (Workers & Pages, projeto `cauri`) ou um domínio próprio, e nunca `cauri.pages.dev`:
nas Redirect URLs do Supabase, ele mandaria o token do magic link para o site de outra pessoa.

Nenhum deles fica no código: o build do Pages monta a CSP com as variáveis `VITE_*`, e o
Nginx recebe o subdomínio por `sed` na instalação.

## 1. Supabase (região São Paulo)

1. Crie o projeto em **South America (São Paulo), sa-east-1**. Guarde a senha do banco num
   gerenciador de senhas; ela compõe o `SUPABASE_DB_URL`. Use só letras e números: a senha
   vai dentro de uma URL, onde `@ : / # ?` quebram a conexão. Esqueceu ou não guardou?
   *Project Settings, Database, Reset database password*.
2. **Migrations:** cadastre o secret `SUPABASE_DB_URL` (seção 5) e rode o workflow
   *Migrations em produção* (Actions, Run workflow). Depois disso ele roda sozinho a cada
   migration nova na `main`. O URI pronto, só faltando a senha, está no botão *Connect*,
   *Session pooler*: `postgresql://postgres.<ref>:[YOUR-PASSWORD]@<host-do-pooler>:5432/postgres`.
3. **Data API** (*Integrations, Data API, Settings*), **depois** das migrations, porque é
   a primeira que cria o schema `marts`:
   - *Exposed schemas*: só `marts` (desmarque `public` e `graphql_public`);
   - *Automatically expose new tables*: desligado. As migrations dão as permissões
     explicitamente, view por view.
   O pg_graphql é removido pela primeira migration.
4. **Senhas dos roles da aplicação** (SQL Editor), uma vez:

   ```sql
   alter role cauri_api with password '<senha-forte-1>';
   alter role cauri_ingest with password '<senha-forte-2>';
   ```

   As conexões usam o pooler (IPv4), com o usuário no formato `role.<ref>`. O host do
   pooler está no botão *Connect* do painel:
   - API: `postgresql://cauri_api.<ref>:<senha-1>@<host-do-pooler>:6543/postgres`
   - jobs: `postgresql://cauri_ingest.<ref>:<senha-2>@<host-do-pooler>:6543/postgres`
   - dono (migrations, preparação, backup): porta **5432** (modo sessão), usuário `postgres.<ref>`.
5. **Auth, URL Configuration:**
   - Site URL: `https://<dominio-do-pages>/app`
   - Redirect URLs: `https://<dominio-do-pages>/**` (só esse; nada de curinga em `*.pages.dev`)
6. **Auth, Hooks:** ative *Before User Created* apontando para a função Postgres
   `app.hook_before_user_created` (a allowlist). Sem isso, qualquer e-mail cria conta.
7. **Auth, SMTP próprio** (o padrão do Supabase manda poucos e-mails por hora e não serve
   para produção), com os dados do Resend (seção 2):
   - Host `smtp.resend.com`, porta `465`, usuário `resend`, senha = chave da API do Resend;
   - Remetente `nao-responda@<dominio-do-email>`, nome `Cauri`.
   Em *Rate Limits*, suba "emails sent per hour" para 30.
8. **Auth, Emails, Templates:** em **Magic link** e em **Confirm signup** (o primeiro acesso
   de um convidado usa este), assunto `Seu link de acesso ao Cauri` e, no corpo, o HTML de
   `supabase/templates/acesso.html`. O link leva a `/entrar?token_hash=...`, e só o clique em
   "Entrar" gasta o código. Com o template padrão, o link é gasto ao abrir (filtros de e-mail
   que pré-abrem links derrubam o acesso) e só funciona no navegador que pediu (PKCE).
9. **JWT Keys** (Settings): a chave atual precisa ser assimétrica (ECC ou RSA), o padrão de
   projeto novo. A API valida o login pelo JWKS público e não precisa de segredo. Se
   aparecer só *Legacy HS256*, migre para a chave nova no próprio painel.
10. **Chave publicável** (Settings, API Keys): a `sb_publishable_...` vai para o Pages. A
    chave secreta (service role) não é usada em lugar nenhum.

**O que me passar depois de criar** (nada disso é segredo): o `<ref>` (Settings, General,
*Project ID*), o `<host-do-pooler>` (botão *Connect*, *Session pooler*) e o tipo da chave
em *JWT Keys*. Senha do banco, senhas dos roles e chaves ficam só com você.

## 2. Resend (e-mail do magic link)

O que você cria lá (plano gratuito: 3.000 e-mails por mês, 100 por dia):

1. Conta em resend.com.
2. **Domínio:** adicione o `<dominio-do-email>` (um subdomínio como `mail.<seu-dominio>`
   isola a reputação do domínio principal) e crie no DNS os registros que o Resend mostrar
   (SPF, DKIM e, se quiser, DMARC). Se o DNS estiver no Cloudflare, dá para criar direto
   pelo botão do Resend. Espere o status *Verified*.
3. **Chave da API:** permissão *Sending access*, restrita a esse domínio. Ela é a senha do
   SMTP no Supabase (passo 1.7) e só fica lá.

## 3. VPS

Passo a passo com os comandos em `deploy/vps/README.md`:

1. Na sua máquina: chave SSH nova só para o deploy, `known_hosts` e os dois secrets
   correspondentes, direto do arquivo para o GitHub com `gh secret set`.
2. Na VPS: usuário `cauri-deploy` sem senha, no grupo `docker`, com a chave presa a um único
   comando (`/usr/local/bin/cauri-deploy`); `/opt/cauri` com os segredos em `api.env`.
3. `api.env` com a conexão do `cauri_api`, a URL do Supabase, o CORS só para
   `https://<dominio-do-pages>` e as chaves da Anthropic e da Groq.
4. Nginx com o subdomínio e `certbot --nginx`.
5. Backup: `docs/backup.md`.

## 4. Cloudflare Pages

1. Conecte o repositório (privado funciona). Projeto `cauri`, branch de produção `main`.
   Para usar o domínio raiz (`seu-dominio.com.br`, sem subdomínio) no Pages, o DNS do
   domínio precisa estar no Cloudflare: adicione o domínio no painel (plano Free) e troque
   os servidores DNS no registro.br pelos dois que o Cloudflare indicar.
2. Build: diretório raiz `web`, comando `npm ci && npm run build`, saída `dist`.
3. Variáveis de ambiente de produção (não são segredos: vão para o navegador):
   - `VITE_SUPABASE_URL=https://<ref>.supabase.co`
   - `VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...`
   - `VITE_API_URL=https://<api.seu-dominio>`
   - `NODE_VERSION=22`
4. O build gera `_headers` com a CSP liberando conexão só para esse Supabase e essa API, e
   `_redirects` para as rotas da SPA. O teste `e2e/csp.spec.ts` confere no CI que a CSP não
   quebra nenhuma tela.

## 5. GitHub: secrets, variável e environment

Crie o environment **production** (Settings, Environments, ou
`gh api -X PUT repos/gl-dias/Cauri/environments/production`). Se quiser aprovação manual
para deploy e migrations, ative nele.

Os secrets dos jobs agendados ficam no **repositório**: o job diário e o monitoramento não
usam o environment (com aprovação manual, eles ficariam esperando alguém todo dia). Os que
mudam produção ficam no **environment** `production`. O *Preparar produção* enxerga os dois.

| Secret | Onde | Usado em | O que é |
|---|---|---|---|
| `CAURI_INGEST_DATABASE_URL` | repositório | `daily-market.yml`, `monitor.yml`, `bootstrap-prod.yml` | conexão do role `cauri_ingest` (porta 6543) |
| `BRAPI_API_KEY` | repositório | `daily-market.yml`, `bootstrap-prod.yml` | token da brapi (fechamento diário) |
| `COINGECKO_API_KEY` | repositório | `daily-market.yml`, `bootstrap-prod.yml` | chave Demo do CoinGecko |
| `SUPABASE_DB_URL` | production | `db-migrate.yml`, `bootstrap-prod.yml` | conexão do dono do banco (`postgres.<ref>`, porta 5432) |
| `ADMIN_EMAIL` | production | `bootstrap-prod.yml` | seu e-mail, que entra na allowlist como admin |
| `VPS_HOST` | production | `deploy-api.yml` | host ou IP da VPS (o mesmo usado no `ssh-keyscan`) |
| `VPS_USER` | production | `deploy-api.yml` | `cauri-deploy` |
| `VPS_PORT` | production | `deploy-api.yml` | porta SSH (opcional; padrão 22) |
| `VPS_SSH_KEY` | production | `deploy-api.yml` | chave privada dedicada ao deploy |
| `VPS_KNOWN_HOSTS` | production | `deploy-api.yml` | saída do `ssh-keyscan` da VPS |

Pelo terminal, sem a chave aparecer na tela: `gh secret set NOME --repo gl-dias/Cauri`
(repositório) ou com `--env production`; o `gh` pede o valor escondido, ou lê de um arquivo
com `< arquivo`.

Variável (não secreta), em Settings, Variables: `API_URL=https://<api.seu-dominio>`, usada
na checagem de saúde depois do deploy.

As chaves da Anthropic e da Groq não vão para o GitHub: só existem no `api.env` da VPS.

## 6. Ordem e checkpoint

1. Supabase (1.1 a 1.4, com as migrations no 1.2).
2. Resend, SMTP e templates de e-mail do Supabase (1.5 a 1.10, 2).
3. Workflow *Preparar produção* (Run workflow, "tudo"): cadastro, ativos, carteira demo,
   admin (`ADMIN_EMAIL`) e histórico de preços.
4. VPS (3) e o workflow *Deploy da API*.
5. Cloudflare Pages (4).
6. Checkpoint:
   - `/demo` abre com a carteira demo e `/app` pede login;
   - o magic link chega no e-mail do admin e entra no `/app`;
   - *Mercado diário* rodado uma vez à mão (Run workflow) termina com sucesso;
   - *Monitoramento* rodado à mão não abre issue.
