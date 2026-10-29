# ADR 0004: API na VPS própria, com Dockerfile portável

Status: aceita (29/10/2026)

## Contexto

O Pages é estático e as Edge Functions do Supabase rodam em Deno, mas importação e
assistente são em Python. A proposta inicial era o Cloud Run. Já existe uma VPS que
roda outros serviços com Docker Compose, Nginx e Certbot, no padrão `/opt/<nome>/`.

## Decisão

- A API roda na VPS, em `/opt/cauri/`, com `restart: unless-stopped`, porta presa em
  `127.0.0.1` e Nginx com TLS na frente (`deploy/vps/`).
- A imagem (`backend/apps/api/Dockerfile`) é portável: multi-stage com uv, instala
  só o pacote `cauri-api`, usuário sem privilégio, porta pela variável `PORT`,
  configuração só por variável de ambiente, nenhum segredo dentro.
- Deploy (Fase 6): o GitHub Actions builda, publica no GHCR e, por SSH com chave
  dedicada, roda `docker compose pull && docker compose up -d`.
- A conexão com o Postgres usa o pooler do Supabase (aceita IPv4), sem prepared
  statements, com `SET LOCAL` dentro de cada transação.

## Consequências

- Custo zero adicional e o mesmo jeito de operar dos outros serviços.
- Sem escala a zero: a API fica sempre no ar (bom para o tempo de resposta).
- Migrar para Cloud Run ou outro host de containers é trocar o destino do deploy,
  sem mexer no código.
- A disponibilidade da escrita depende da VPS; a leitura (ADR 0001) não.
