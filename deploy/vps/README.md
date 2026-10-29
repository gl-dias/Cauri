# API do Cauri na VPS

A API (FastAPI) roda num container, no mesmo padrão dos outros serviços da VPS:
`/opt/<nome>/` com Docker Compose, `restart: unless-stopped`, Nginx na frente e TLS
pelo Certbot. A imagem é a mesma que rodaria no Cloud Run (ver `backend/apps/api/Dockerfile`).

## Primeira instalação

1. Pasta e arquivos:

   ```bash
   sudo mkdir -p /opt/cauri && cd /opt/cauri
   # copie deploy/vps/docker-compose.yml para cá
   sudo touch .env && sudo chmod 600 .env
   ```

2. Preencha o `.env` (modelo em `.env.example`, seção API):

   ```dotenv
   GHCR_OWNER=<usuario-ou-org-do-github>
   CAURI_API_TAG=latest
   CAURI_DATABASE_URL=postgresql://cauri_api.<ref>:<senha>@<pooler>.pooler.supabase.com:6543/postgres
   CAURI_SUPABASE_URL=https://<ref>.supabase.co
   CAURI_CORS_ORIGINS=["https://<projeto>.pages.dev"]
   ANTHROPIC_API_KEY=<chave-da-anthropic>
   GROQ_API_KEY=<chave-do-groq>
   ```

   A conexão usa o role `cauri_api` (nunca o dono do banco) pelo pooler do Supabase,
   que aceita IPv4. A senha do role é definida uma vez no SQL Editor do Supabase:
   `alter role cauri_api with password '...'`.

3. Se a imagem no GHCR for privada, faça login com um token de leitura de pacotes:

   ```bash
   echo "<token>" | docker login ghcr.io -u <usuario> --password-stdin
   ```

   Se o pacote for público (o repositório é), não precisa.

4. Suba e confira:

   ```bash
   docker compose up -d
   curl -s http://127.0.0.1:8010/health   # {"status":"ok"}
   ```

5. Nginx e TLS: use `nginx/cauri-api.conf` como base (instruções no próprio arquivo)
   e rode `sudo certbot --nginx -d api.SEU-DOMINIO`.

## Deploy automático

`.github/workflows/deploy-api.yml`: push na `main` que mexe no `backend/` (ou Run workflow)
builda a imagem, publica em `ghcr.io/gl-dias/cauri-api:<sha>` e `:latest`, e por SSH (chave
dedicada, secrets `VPS_HOST`, `VPS_USER`, `VPS_PORT`, `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`)
atualiza o `CAURI_API_TAG` do `.env`, faz `docker compose pull` e `up -d`. O token do
próprio job autentica a VPS no GHCR durante o deploy e expira com ele, então a imagem pode
ficar privada. No fim, confere `GET $API_URL/health`.

## Backup

`docs/backup.md`: dump semanal dos schemas de dados para `/opt/cauri/backups`, retenção de
8 semanas e o teste de restauração.
