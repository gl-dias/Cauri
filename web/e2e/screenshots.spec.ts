import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { mockDemo } from "./mocks";

// Saída fora do repositório por padrão: as comparações usam frames de referência de
// terceiros, que nunca vão para o git.
const OUT = process.env.CAURI_SHOTS_DIR ?? path.resolve("..", "reference-private", "review");
mkdirSync(OUT, { recursive: true });

async function ready(page: import("@playwright/test").Page) {
  await expect(page.getByText("Patrimônio total")).toBeVisible();
  await expect(page.getByText("Últimas movimentações")).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600); // foto de fundo e gráficos
  // Sem rolagem horizontal em nenhuma largura.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("Início do demo", async ({ page }, info) => {
  await mockDemo(page);
  await page.goto("/demo");
  await ready(page);
  await page.screenshot({ path: path.join(OUT, `inicio-${info.project.name}-dobra.png`) });
  // Página inteira: a janela cresce até a altura do conteúdo para a foto fixa cobrir tudo,
  // como fica para quem rola a página.
  const viewport = page.viewportSize()!;
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.setViewportSize({ width: viewport.width, height });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, `inicio-${info.project.name}.png`) });
});
