import { mkdirSync } from "node:fs";
import path from "node:path";

import { test } from "@playwright/test";

import { openScreen, SCREENS } from "./screens";

// Saída fora do repositório por padrão (reference-private/ é ignorado). Os screenshots do
// README saem só do /demo, na Fase 6.
const OUT = process.env.CAURI_SHOTS_DIR ?? path.resolve("..", "reference-private", "review");
mkdirSync(OUT, { recursive: true });

for (const screen of SCREENS) {
  test(`screenshot: ${screen.name}`, async ({ page }, info) => {
    await openScreen(page, screen);
    await page.screenshot({ path: path.join(OUT, `${screen.name}-${info.project.name}-dobra.png`) });
    // Página inteira: a janela cresce até a altura do conteúdo para a foto fixa cobrir tudo.
    if (!screen.name.includes("novo-lancamento") && screen.name !== "login") {
      const viewport = page.viewportSize()!;
      const height = await page.evaluate(() => document.documentElement.scrollHeight);
      await page.setViewportSize({ width: viewport.width, height });
      await page.waitForTimeout(400);
      await page.screenshot({ path: path.join(OUT, `${screen.name}-${info.project.name}.png`) });
    }
  });
}
