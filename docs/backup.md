# Backup e restauração

## O que é guardado

Toda semana, na VPS, `deploy/vps/backup/cauri-backup.sh` gera em `/opt/cauri/backups`:

- `cauri-AAAA-MM-DD.dump`: `pg_dump` no formato custom dos schemas de dados `app`, `ledger`,
  `imports`, `assistant`, `market`, `engine` e `ops`. Fica de fora o `raw` (respostas cruas
  das fontes, que o job refaz) e o schema `auth` inteiro.
- `cauri-AAAA-MM-DD-usuarios.csv`: só `id`, `email` e `created_at` das contas, sem senha,
  sem token e sem sessão. Sem ele, uma restauração num projeto novo criaria contas com ids
  novos e os dados ficariam sem dono.
- `cauri-AAAA-MM-DD-contagens.txt`: linhas de cada tabela, para conferir a restauração.

Retenção de 8 semanas; arquivos e pasta só legíveis pelo root (600 e 700).

## Instalação na VPS

Com os arquivos de `deploy/vps` copiados para `/tmp/cauri-vps` (passo 1 de
`deploy/vps/README.md`):

```bash
SRC=/tmp/cauri-vps
sudo install -d -o root -g root -m 700 /opt/cauri/backup /opt/cauri/backups
sudo install -o root -g root -m 700 "$SRC/backup/cauri-backup.sh" /opt/cauri/backup/cauri-backup.sh
sudo install -o root -g root -m 600 /dev/null /opt/cauri/backup.env
sudo nano /opt/cauri/backup.env
#   CAURI_BACKUP_DATABASE_URL=postgresql://postgres.<ref>:<senha-do-banco>@<host-do-pooler>:5432/postgres
sudo install -o root -g root -m 644 "$SRC/backup/cauri-backup.cron" /etc/cron.d/cauri-backup
sudo /opt/cauri/backup/cauri-backup.sh   # primeira execução, para conferir
```

O `backup.env` fica só com o root: o usuário `cauri-deploy` não lê a senha do dono do banco.

O script roda o `pg_dump` dentro do container `postgres:17-alpine` (mesma versão maior do
Supabase), então a VPS só precisa do Docker.

## Teste de restauração

`deploy/vps/backup/restore-check.sh` simula a restauração num projeto novo do Supabase, no
Supabase local (ele recusa qualquer banco que não seja local):

1. banco limpo com todas as migrations (`supabase db reset`);
2. contas recriadas com o mesmo id e e-mail a partir do CSV (com a identidade de e-mail,
   para o magic link funcionar);
3. dados carregados com o `pg_restore` numa sessão com os triggers desligados (o ledger
   proíbe remoção e edição fora das regras, o que não faz sentido numa carga);
4. contagem de cada tabela comparada com o manifesto do backup.

```bash
scp vps:/opt/cauri/backups/cauri-AAAA-MM-DD* ./restauracao/
deploy/vps/backup/restore-check.sh ./restauracao/cauri-AAAA-MM-DD.dump
```

### Execução registrada (29/10/2026)

Com o banco local de desenvolvimento como origem:

- backup: 2,2 MB, 30 tabelas, CSV com as contas;
- restauração completa em 41 s: "30 tabelas com as mesmas contagens do backup";
- depois da restauração, os 7 testes ao vivo (`just e2e-live`) passaram: o admin entrou pelo
  magic link com o mesmo id e viu os dados de antes, importou, usou o assistente.

Dois ajustes saíram desse teste e estão no script: as colunas de token do `auth.users`
precisam ser texto vazio (com nulo o Auth não acha a conta e o magic link falha), e o
`postgres` do Supabase não desliga triggers com `--disable-triggers`, então a carga usa
`session_replication_role = replica` dentro da sessão.

## Restauração de verdade (projeto novo)

1. Projeto novo no Supabase e o workflow *Migrations em produção* apontando para ele.
2. Passos 2 a 4 do teste acima, com `CAURI_RESTORE_DATABASE_URL` apontando para o novo
   banco: o script só aceita banco local, então para produção rode os mesmos comandos à mão
   (ou tire a trava conscientemente, num terminal só para isso).
3. Senhas dos roles, URLs do Auth, hook e SMTP como em `docs/deploy.md`.
4. Atualize os secrets do GitHub e o `api.env` da VPS com o novo projeto.
