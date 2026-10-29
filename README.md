# Cauri

Portal de investimentos pessoal, modular, para poucos usuários convidados: ações e FIIs
da B3, Tesouro Direto, renda fixa atrelada ao CDI e cripto, com registro de
movimentações por planilha, cadastro manual e linguagem natural.

> Em construção. Fase 1 de 6 (fundação) entregue. O README de portfólio, com
> screenshots e link para o `/demo`, chega na Fase 6.

- Arquitetura, schema e fluxo de deploy: [`docs/arquitetura.md`](docs/arquitetura.md)
- Decisões técnicas: [`docs/adr/`](docs/adr/)

## Rodando localmente

Requer [uv](https://docs.astral.sh/uv/), [just](https://just.systems/), Docker e a
[CLI do Supabase](https://supabase.com/docs/guides/local-development).

```sh
cp .env.example .env
just db-start      # Supabase local
just sync          # dependências Python
just seed          # ativos, carteira demo com preços reais e admin inicial
just check         # lint, tipos, fronteiras entre módulos e testes
just api           # API em http://127.0.0.1:8000
```
