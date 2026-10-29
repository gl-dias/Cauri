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
