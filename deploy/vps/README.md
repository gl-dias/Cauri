# API do Cauri na VPS

A API (FastAPI) roda num container, no mesmo padrão dos outros serviços da VPS:
`/opt/<nome>/` com Docker Compose, `restart: unless-stopped`, Nginx na frente e TLS
pelo Certbot. A imagem é a mesma que rodaria no Cloud Run (ver `backend/apps/api/Dockerfile`).

## Como fica

| Caminho | Dono e modo | O que é |
|---|---|---|
| `/opt/cauri/docker-compose.yml` | root, 644 | serviço da API |
| `/opt/cauri/.env` | cauri-deploy, 644 | só `GHCR_OWNER` e `CAURI_API_TAG`, sem segredo; o deploy reescreve a tag |
| `/opt/cauri/api.env` | root:cauri-deploy, 640 | segredos da API |
| `/usr/local/bin/cauri-deploy` | root, 755 | único comando que a chave de deploy pode rodar |
| `/home/cauri-deploy/.ssh/authorized_keys` | root, 644 | a chave do GitHub, presa a esse comando |

**Por que assim:** quem está no grupo `docker` tem, na prática, poder de root na máquina.
Então o limite de verdade não é o grupo, é a chave: no `authorized_keys` ela fica com
`restrict,command="/usr/local/bin/cauri-deploy"`, sem shell, sem túnel e sem outro
comando. Se a chave vazar, o máximo que dá para fazer com ela é publicar de novo uma imagem
que já está no GHCR do repositório. O usuário não tem senha e não escreve em nada além do
`.env` da tag.

## Instalação

Os comandos usam estas variáveis; preencha antes de colar:

```bash
VPS=<usuario-admin>@<host-ou-ip>      # seu acesso de administrador
PORTA=22                             # porta SSH da VPS
API_DOMAIN=<api.seu-dominio>          # subdomínio da API (DNS já apontando para a VPS)
```

### 1. Na sua máquina: chave de deploy, known_hosts e secrets

No Git Bash ou no terminal do Mac, numa pasta fora do repositório. As chaves vão direto do
arquivo para o GitHub pelo `gh`, sem passar por chat nem pela tela.

```bash
gh api -X PUT repos/gl-dias/Cauri/environments/production >/dev/null   # cria o environment

ssh-keygen -t ed25519 -N "" -C "cauri-deploy@github-actions" -f ./cauri-deploy
gh secret set VPS_SSH_KEY --env production --repo gl-dias/Cauri < ./cauri-deploy

ssh-keyscan -p "$PORTA" -t ed25519 <host-ou-ip> > ./cauri-known_hosts
ssh-keygen -lf ./cauri-known_hosts      # anote a impressão digital (confere no passo 2)
gh secret set VPS_KNOWN_HOSTS --env production --repo gl-dias/Cauri < ./cauri-known_hosts

scp -P "$PORTA" ./cauri-deploy.pub "$VPS":/tmp/cauri-deploy.pub
scp -P "$PORTA" -r deploy/vps "$VPS":/tmp/cauri-vps   # rode este da raiz do repositório
```

Use em `VPS_HOST` exatamente o host ou IP que foi para o `ssh-keyscan`.

### 2. Na VPS: usuário, permissões e comando de deploy

```bash
API_DOMAIN=<api.seu-dominio>
SRC=/tmp/cauri-vps

# Confere se a impressão digital é a mesma do passo 1 (evita known_hosts de outra máquina).
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub

# Usuário sem senha (entra só por chave), no grupo docker.
sudo useradd --create-home --shell /bin/bash cauri-deploy
sudo usermod -p '*' cauri-deploy
sudo usermod -aG docker cauri-deploy

# Único comando que a chave pode rodar.
sudo install -o root -g root -m 755 "$SRC/cauri-deploy.sh" /usr/local/bin/cauri-deploy

# Chave presa ao comando; arquivo do root, o usuário não consegue trocar.
sudo install -d -o root -g root -m 755 /home/cauri-deploy/.ssh
printf 'restrict,command="/usr/local/bin/cauri-deploy" %s\n' "$(cat /tmp/cauri-deploy.pub)" \
  | sudo tee /home/cauri-deploy/.ssh/authorized_keys >/dev/null
sudo chmod 644 /home/cauri-deploy/.ssh/authorized_keys
rm /tmp/cauri-deploy.pub

# /opt/cauri: root é dono; cauri-deploy lê os segredos e reescreve só a tag.
sudo install -d -o root -g root -m 755 /opt/cauri
sudo install -o root -g root -m 644 "$SRC/docker-compose.yml" /opt/cauri/docker-compose.yml
sudo install -o cauri-deploy -g cauri-deploy -m 644 /dev/null /opt/cauri/.env
printf 'GHCR_OWNER=gl-dias\nCAURI_API_TAG=latest\n' | sudo tee /opt/cauri/.env >/dev/null
sudo install -o root -g cauri-deploy -m 640 /dev/null /opt/cauri/api.env
sudo nano /opt/cauri/api.env   # conteúdo no passo 3

# Se o sshd tiver lista de usuários permitidos, inclua cauri-deploy nela.
sudo sshd -T | grep -Ei '^(allowusers|allowgroups)' || echo "sem lista: nada a fazer"
```

### 3. `/opt/cauri/api.env`

Preencha com os dados do Supabase de produção (modelo completo na seção API do
`.env.example`):

```dotenv
CAURI_DATABASE_URL=postgresql://cauri_api.<ref>:<senha-do-cauri_api>@<host-do-pooler>:6543/postgres
CAURI_SUPABASE_URL=https://<ref>.supabase.co
CAURI_CORS_ORIGINS=["https://cauri.pages.dev"]
ANTHROPIC_API_KEY=<chave-da-anthropic>
GROQ_API_KEY=<chave-do-groq, opcional: sem ela o navegador transcreve>
CAURI_ASSISTANT_DAILY_LIMIT=50
```

A conexão usa o role `cauri_api` (nunca o dono do banco) pelo pooler, que aceita IPv4. O
CORS libera só o domínio do Pages.

### 4. Nginx e TLS

Com o DNS do `API_DOMAIN` apontando para a VPS (no Cloudflare, deixe "DNS only" pelo menos
até o Certbot emitir o certificado):

```bash
sed "s/api\.SEU-DOMINIO/$API_DOMAIN/g" "$SRC/nginx/cauri-api.conf" \
  | sudo tee /etc/nginx/sites-available/cauri-api.conf >/dev/null
sudo ln -sf /etc/nginx/sites-available/cauri-api.conf /etc/nginx/sites-enabled/cauri-api.conf
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d "$API_DOMAIN"
```

### 5. Teste da chave e primeiro deploy

Na sua máquina, a chave precisa ser recusada para qualquer coisa que não seja o deploy:

```bash
ssh -i ./cauri-deploy -p "$PORTA" cauri-deploy@<host-ou-ip> whoami
# uso: deploy <sha do commit> <usuario do github>
rm ./cauri-deploy ./cauri-deploy.pub ./cauri-known_hosts   # a chave já está no GitHub
```

Depois, no GitHub: secrets `VPS_HOST`, `VPS_USER` (`cauri-deploy`) e, se não for 22,
`VPS_PORT`; variável `API_URL=https://<api.seu-dominio>`; e Actions, *Deploy da API*,
Run workflow. Na VPS, `rm -rf /tmp/cauri-vps` quando terminar (o backup usa os scripts de
lá, ver abaixo).

## Deploy automático

`.github/workflows/deploy-api.yml`: push na `main` que mexe no `backend/` (ou Run workflow)
builda a imagem, publica em `ghcr.io/gl-dias/cauri-api:<sha>` e `:latest` e chama
`ssh cauri-deploy@vps deploy <sha> <usuario>`. O `cauri-deploy` faz login no GHCR com o
token do próprio job (que chega pelo stdin e expira com ele, então a imagem pode ficar
privada), baixa a imagem, sobe a API e só então grava a tag no `.env`. Guarda a imagem
atual e a anterior. No fim, o workflow confere `GET $API_URL/health`.

**Voltar para a versão anterior** (como administrador; a imagem anterior está na VPS):

```bash
cd /opt/cauri
sudo docker images ghcr.io/gl-dias/cauri-api       # as duas tags guardadas
# tee mantém o dono (cauri-deploy); sed -i trocaria para root e travaria o próximo deploy
printf 'GHCR_OWNER=gl-dias\nCAURI_API_TAG=%s\n' <sha-anterior> | sudo tee .env >/dev/null
sudo docker compose up -d api
```

## Backup

`docs/backup.md`: dump semanal dos schemas de dados para `/opt/cauri/backups`, retenção de
8 semanas e o teste de restauração. Instale antes de apagar o `/tmp/cauri-vps`.
