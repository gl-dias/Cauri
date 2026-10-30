/**
 * Entrada pelo link do e-mail (/entrar?token_hash=...), com o Supabase simulado. O código só
 * pode ser gasto no clique de "Entrar": um filtro de e-mail que abre o link sozinho não
 * consome o acesso, e a sessão nasce do verifyOtp, sem depender do navegador que pediu.
 */
import { expect, test, type Request } from "@playwright/test";

import { LIVE, mockApp } from "./mocks";

test.skip(LIVE, "fluxo simulado; o ao vivo está em app-live.spec.ts");

test("abrir o link não gasta o código; o clique em Entrar cria a sessão", async ({ page }) => {
  await mockApp(page, { signedIn: false });
  const verifies: Request[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/auth/v1/verify")) verifies.push(req);
  });

  await page.goto("/entrar?token_hash=abc123&type=email");
  await expect(page.getByRole("heading", { name: "Entrar no Cauri" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(verifies).toHaveLength(0);

  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByText("Patrimônio total").first()).toBeVisible();
  expect(verifies).toHaveLength(1);
  expect(verifies.at(0)?.postDataJSON()).toMatchObject({ token_hash: "abc123", type: "email" });
});

test("link expirado ou já usado explica e oferece outro", async ({ page }) => {
  await mockApp(page, { signedIn: false });
  await page.route(/\/auth\/v1\/verify/, (route) =>
    route.fulfill({
      status: 403,
      json: { code: 403, error_code: "otp_expired", msg: "Email link is invalid or has expired" },
    }),
  );

  await page.goto("/entrar?token_hash=velho&type=email");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("alert")).toContainText("Esse link já foi usado ou passou de 1 hora");
  await page.getByRole("link", { name: "Pedir outro link" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("link que caiu no /app (endereço padrão do Supabase) segue para /entrar", async ({ page }) => {
  await mockApp(page, { signedIn: false });
  await page.goto("/app?token_hash=abc123&type=email");
  await expect(page).toHaveURL(/\/entrar\?token_hash=abc123&type=email$/);
  await expect(page.getByRole("button", { name: "Entrar" })).toBeVisible();
});

test("sem código, /entrar volta para o login", async ({ page }) => {
  await mockApp(page, { signedIn: false });
  await page.goto("/entrar");
  await expect(page).toHaveURL(/\/login$/);
});
