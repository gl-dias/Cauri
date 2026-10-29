/**
 * Ponta a ponta de verdade (CAURI_E2E_LIVE=1): Supabase local, API local e Mailpit.
 * Login por magic link de um convidado fictício, lançamento manual gravado pela API, tela
 * de admin e a allowlist barrando quem não foi convidado. Pré-requisitos:
 *   supabase start; cauri-jobs bootstrap-admin (CAURI_ADMIN_EMAIL=e2e-admin@example.test);
 *   uvicorn da API na porta 8000; npm run dev.
 */
import { expect, test, type Page } from "@playwright/test";

import { LIVE } from "./mocks";

const MAILPIT = "http://127.0.0.1:54324/api/v1";
const ADMIN = "e2e-admin@example.test";

type MailSummary = { ID: string; To: { Address: string }[]; Created: string };

async function messagesTo(address: string, since: number): Promise<MailSummary[]> {
  const res = await fetch(`${MAILPIT}/messages?limit=50`);
  const body = (await res.json()) as { messages: MailSummary[] };
  return body.messages.filter(
    (m) => m.To.some((t) => t.Address.toLowerCase() === address) && Date.parse(m.Created) >= since,
  );
}

async function magicLink(address: string, since: number): Promise<string> {
  for (let i = 0; i < 30; i++) {
    const [latest] = await messagesTo(address, since);
    if (latest) {
      const res = await fetch(`${MAILPIT}/message/${latest.ID}`);
      const msg = (await res.json()) as { HTML: string; Text: string };
      const match = `${msg.HTML} ${msg.Text}`.match(/https?:\/\/127\.0\.0\.1:54321\/auth\/v1\/verify\?[^\s"'<>]+/);
      if (match) return match[0].replace(/&amp;/g, "&");
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`nenhum magic link para ${address}`);
}

async function requestLink(page: Page, address: string) {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(address);
  await page.getByRole("button", { name: "Enviar link de acesso" }).click();
  await expect(page.getByText("Confira seu e-mail")).toBeVisible();
}

test.describe("ao vivo", () => {
  test.skip(!LIVE, "só roda com CAURI_E2E_LIVE=1 (Supabase, API e Mailpit locais)");
  test.beforeEach(({}, info) => test.skip(info.project.name !== "desktop", "fluxo testado uma vez, no desktop"));

  test("convidado entra pelo magic link, grava um lançamento e vê o admin", async ({ page }) => {
    const since = Date.now() - 1000;
    await requestLink(page, ADMIN);
    await page.goto(await magicLink(ADMIN, since));
    await expect(page).toHaveURL(/\/app/);
    await expect(page.getByRole("link", { name: "Admin" }).first()).toBeVisible();

    await page.goto("/app/lancamentos");
    await page.getByRole("button", { name: "Novo lançamento" }).click();
    const dialog = page.getByRole("dialog", { name: "Novo lançamento" });
    await dialog.getByLabel("Ativo").fill("PETR4");
    await dialog.getByLabel("Corretora").selectOption({ label: "XP Investimentos" });
    await dialog.getByLabel("Quantidade").fill("1");
    await dialog.getByLabel("Preço unitário (R$)").fill("30,00");
    await dialog.getByRole("button", { name: "Conferir" }).click();
    await expect(dialog.getByText("Tudo certo para gravar.")).toBeVisible();
    await dialog.getByRole("button", { name: "Confirmar lançamento" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("cell", { name: /PETR4/ }).first()).toBeVisible();

    await page.goto("/app/admin");
    await expect(page.getByText(ADMIN)).toBeVisible();

    await page.getByRole("button", { name: "Conta" }).click();
    await page.getByRole("button", { name: "Sair" }).click();
    await page.goto("/app");
    await expect(page).toHaveURL(/\/login/);
  });

  test("importa uma planilha pela tela e o reenvio não duplica", async ({ page }) => {
    const since = Date.now() - 1000;
    await requestLink(page, ADMIN);
    await page.goto(await magicLink(ADMIN, since));
    await expect(page).toHaveURL(/\/app/);

    // Preço único por execução: cada rodada é uma operação nova para o ledger.
    const price = (30 + (Date.now() % 1000) / 100).toFixed(2).replace(".", ",");
    const csv = Buffer.from(
      `data;tipo;ativo;classe;quantidade;preco;corretora\n02/03/2026;compra;PETR4;acao;1;${price};XP Investimentos\n`,
    );
    const pick = async () => {
      await page.goto("/app/importar");
      await page.getByLabel("Escolher arquivos").setInputFiles({ name: "teste-e2e.csv", mimeType: "text/csv", buffer: csv });
      await page.getByRole("button", { name: "Pré-visualizar" }).click();
    };

    await pick();
    await expect(page.getByText("pronta").first()).toBeVisible();
    await page.getByRole("button", { name: "Importar 1" }).click();
    await expect(page.getByText("1 movimentação importada")).toBeVisible();

    await pick();
    await expect(page.getByText("já importada").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Importar 0" })).toBeDisabled();
    await page.getByRole("button", { name: "Descartar" }).click();
    await expect(page.getByText("Arraste os arquivos aqui")).toBeVisible();
  });

  test("arquivo desconhecido vira perfil e passa a ser reconhecido", async ({ page }) => {
    const since = Date.now() - 1000;
    await requestLink(page, ADMIN);
    await page.goto(await magicLink(ADMIN, since));
    await expect(page).toHaveURL(/\/app/);

    // Cabeçalho único por execução: o perfil é sempre novo e é apagado no fim.
    const run = Date.now().toString(36);
    const name = `Corretora e2e ${run}`;
    const csv = Buffer.from(`Dia;Natureza;Papel ${run};Qtde;Preço\n02/03/2026;C;PETR4;1;31,00\n`);
    const pick = async () => {
      await page.goto("/app/importar");
      await page.getByLabel("Escolher arquivos").setInputFiles({ name: "extrato-e2e.csv", mimeType: "text/csv", buffer: csv });
      await page.getByRole("button", { name: "Pré-visualizar" }).click();
    };

    await pick();
    await expect(page.getByText("Formato novo: extrato-e2e.csv")).toBeVisible();
    await page.getByLabel("Ativo *").selectOption(`Papel ${run}`);
    await page.getByLabel("Corretora fixa").selectOption({ label: "XP Investimentos" });
    await page.getByLabel("Nome do perfil").fill(name);
    await page.getByRole("button", { name: "Salvar perfil e pré-visualizar" }).click();
    await expect(page.getByText(`Perfil ${name}`)).toBeVisible();
    await page.getByRole("button", { name: "Descartar" }).click();

    // Da próxima vez, o arquivo é reconhecido direto pelo perfil.
    await pick();
    await expect(page.getByText(`Perfil ${name}`)).toBeVisible();
    await page.getByRole("button", { name: "Descartar" }).click();

    await page.getByRole("button", { name: `Apagar o perfil ${name}` }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Apagar" }).click();
    await expect(page.getByRole("button", { name: `Apagar o perfil ${name}` })).toBeHidden();
  });

  test("e-mail fora da allowlist vê a mesma mensagem e não recebe link", async ({ page }) => {
    const outsider = `nao-convidado-${Date.now()}@example.test`;
    const since = Date.now() - 1000;
    await requestLink(page, outsider);
    await page.waitForTimeout(3000);
    expect(await messagesTo(outsider, since)).toEqual([]);
  });

  test("sem sessão, o /app manda para o login e o /demo segue público", async ({ page }) => {
    await page.goto("/app/carteira");
    await expect(page).toHaveURL(/\/login/);
    await page.goto("/demo");
    await expect(page.getByText("Patrimônio total")).toBeVisible();
  });
});
