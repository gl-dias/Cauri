# Produção

Roteiro para subir o Cauri do zero. O que precisa de conta ou de chave é feito por você
nos painéis; o resto é workflow do GitHub. Nenhuma chave passa pelo chat nem entra no repo.

```
Cloudflare Pages (/demo, /app)  ──►  Supabase sa-east-1 (Postgres, Auth, PostgREST)
        │                                  ▲
        └──►  API na VPS (api.<domínio>) ──┘   GitHub Actions: migrations, deploy da API,
              Nginx + Certbot, Docker              job diário, monitoramento
```

## 1. Supabase (região São Paulo)

1. Crie o projeto em **South America (São Paulo), sa-east-1**. Guarde a senha do banco num
   gerenciador de senhas; ela compõe o `SUPABASE_DB_URL`.
2. **Data API** (Settings, API): em *Exposed schemas* deixe só `marts`. O pg_graphql é
   removido pela primeira migration.
3. **Migrations:** cadastre o secret `SUPABASE_DB_URL` (seção 5) e rode o workflow
   *Migrations em produção* (Actions, Run workflow). Depois disso ele roda sozinho a cada
   migration nova na `main`.
4. **Senhas dos roles da aplicação** (SQL Editor), uma vez:

   ```sql
   alter role cauri_api with password '<senha-forte-1>';
   alter role cauri_ingest with password '<senha-forte-2>';
   ```

   As conexões usam o pooler (IPv4), com o usuário no formato `role.<ref>`:
   - API: `postgresql://cauri_api.<ref>:<senha-1>@aws-0-sa-east-1.pooler.supabase.com:6543/postgres`
   - jobs: `postgresql://cauri_ingest.<ref>:<senha-2>@aws-0-sa-east-1.pooler.supabase.com:6543/postgres`
   - dono (migrations, preparação, backup): porta **5432** (modo sessão), usuário `postgres.<ref>`.
5. **Auth, URL Configuration:**
   - Site URL: `https://<projeto>.pages.dev/app`
   - Redirect URLs: `https://<projeto>.pages.dev/**` (e o domínio próprio, se houver).
6. **Auth, Hooks:** ative *Before User Created* apontando para a função Postgres
   `app.hook_before_user_created` (a allowlist). Sem isso, qualquer e-mail cria conta.
7. **Auth, SMTP próprio** (o padrão do Supabase manda poucos e-mails por hora e não serve
   para produção), com os dados do Resend (seção 2):
   - Host `smtp.resend.com`, porta `465`, usuário `resend`, senha = chave da API do Resend;
   - Remetente `nao-responda@<domínio>`, nome `Cauri`.
   Em *Rate Limits*, suba "emails sent per hour" para 30.
8. **Chave publicável** (Settings, API Keys): a `sb_publishable_...` vai para o Pages. A
   chave secreta (service role) não é usada em lugar nenhum.

## 2. Resend (e-mail do magic link)

O que você cria lá (plano gratuito: 3.000 e-mails por mês, 100 por dia):

1. Conta em resend.com.
2. **Domínio:** adicione o seu domínio (ou um subdomínio, como `mail.<domínio>`) e crie no
   DNS os registros que o Resend mostrar (SPF, DKIM e, se quiser, DMARC). Se o DNS estiver
   no Cloudflare, dá para criar direto pelo botão do Resend. Espere o status *Verified*.
3. **Chave da API:** permissão *Sending access*, restrita a esse domínio. Ela é a senha do
   SMTP no Supabase (passo 1.7) e só fica lá.

## 3. VPS

Tudo em `/opt/cauri`, no padrão dos outros serviços. Detalhes em `deploy/vps/README.md`.

1. Usuário de deploy com chave SSH dedicada e no grupo `docker`. A chave privada vira o
   secret `VPS_SSH_KEY`; `ssh-keyscan -p <porta> <host>` dá o `VPS_KNOWN_HOSTS`.
2. `/opt/cauri/docker-compose.yml` (de `deploy/vps/`) e `/opt/cauri/.env` (chmod 600):

   ```dotenv
   GHCR_OWNER=gl-dias
   CAURI_API_TAG=latest
   CAURI_DATABASE_URL=<conexão do cauri_api, porta 6543>
   CAURI_SUPABASE_URL=https://<ref>.supabase.co
   CAURI_CORS_ORIGINS=["https://<projeto>.pages.dev"]
   ANTHROPIC_API_KEY=<chave>
   GROQ_API_KEY=<chave, opcional: sem ela o navegador transcreve>
   CAURI_ASSISTANT_DAILY_LIMIT=50
   ```

   O CORS libera só o domínio do Pages.
3. Nginx com `deploy/vps/nginx/cauri-api.conf` (troque `api.SEU-DOMINIO`) e
   `sudo certbot --nginx -d api.<domínio>`.
4. Backup: `docs/backup.md`.

## 4. Cloudflare Pages

1. Conecte o repositório (privado funciona). Projeto `<projeto>`.
2. Build: diretório raiz `web`, comando `npm ci && npm run build`, saída `dist`.
3. Variáveis de ambiente (não são segredos: vão para o navegador):
   - `VITE_SUPABASE_URL=https://<ref>.supabase.co`
   - `VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...`
   - `VITE_API_URL=https://api.<domínio>`
   - `NODE_VERSION=22`
4. O build gera `_headers` com a CSP liberando conexão só para esse Supabase e essa API, e
   `_redirects` para as rotas da SPA. O teste `e2e/csp.spec.ts` confere no CI que a CSP não
   quebra nenhuma tela.

## 5. GitHub: secrets, variável e environment

Crie o environment **production** (Settings, Environments; se quiser, com aprovação manual).
Os secrets ficam nele ou no repositório:

| Secret | Usado em | O que é |
|---|---|---|
| `SUPABASE_DB_URL` | `db-migrate.yml`, `bootstrap-prod.yml` | conexão do dono do banco (`postgres.<ref>`, porta 5432) |
| `CAURI_INGEST_DATABASE_URL` | `daily-market.yml`, `monitor.yml`, `bootstrap-prod.yml` | conexão do role `cauri_ingest` (porta 6543) |
| `BRAPI_API_KEY` | `daily-market.yml`, `bootstrap-prod.yml` | token da brapi (fechamento diário) |
| `COINGECKO_API_KEY` | `daily-market.yml`, `bootstrap-prod.yml` | chave Demo do CoinGecko |
| `ADMIN_EMAIL` | `bootstrap-prod.yml` | seu e-mail, que entra na allowlist como admin |
| `VPS_HOST` | `deploy-api.yml` | host ou IP da VPS |
| `VPS_USER` | `deploy-api.yml` | usuário de deploy |
| `VPS_PORT` | `deploy-api.yml` | porta SSH (opcional; padrão 22) |
| `VPS_SSH_KEY` | `deploy-api.yml` | chave privada dedicada ao deploy |
| `VPS_KNOWN_HOSTS` | `deploy-api.yml` | saída do `ssh-keyscan` da VPS |

Variável (não secreta), em Settings, Variables: `API_URL=https://api.<domínio>`, usada na
checagem de saúde depois do deploy.

As chaves da Anthropic e da Groq não vão para o GitHub: só existem no `.env` da VPS.

## 6. Ordem e checkpoint

1. Supabase (1.1 a 1.4) e o workflow *Migrations em produção*.
2. Resend e SMTP do Supabase (1.5 a 1.7, 2).
3. Workflow *Preparar produção* (Run workflow, "tudo"): cadastro, ativos, carteira demo,
   admin (`ADMIN_EMAIL`) e histórico de preços.
4. VPS (3) e o workflow *Deploy da API*.
5. Cloudflare Pages (4).
6. Checkpoint:
   - `/demo` abre com a carteira demo e `/app` pede login;
   - o magic link chega no e-mail do admin e entra no `/app`;
   - *Mercado diário* rodado uma vez à mão (Run workflow) termina com sucesso;
   - *Monitoramento* rodado à mão não abre issue.
