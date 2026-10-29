/**
 * A CSP que vai para o Cloudflare Pages (dist/_headers, gerado no build) não pode quebrar
 * nenhuma tela. O teste aplica o cabeçalho de verdade nas páginas e falha se o navegador
 * recusar qualquer script, estilo, fonte, imagem ou conexão.
 */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { openScreen, SCREENS } from "./screens";

// Lido na hora do teste: no CI, o dist/ é gerado pelo webServer, depois da coleta.
function productionCsp(): string | undefined {
  const file = path.resolve("dist", "_headers");
  return existsSync(file) ? readFileSync(file, "utf-8").match(/Content-Security-Policy: (.+)/)?.[1] : undefined;
}

for (const screen of SCREENS.filter((s) => ["demo-inicio", "demo-carteira", "demo-assistente", "app-importar-previa", "app-assistente"].includes(s.name))) {
  test(`CSP de produção: ${screen.name}`, async ({ page }, info) => {
    test.skip(!process.env.CI, "só contra o build de produção (CI=1): o servidor de desenvolvimento injeta scripts inline");
    const csp = productionCsp();
    test.skip(!csp, "sem dist/_headers (rode o build)");
    test.skip(info.project.name !== "desktop", "a CSP é a mesma no celular");
    const violations: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" && /Content Security Policy|Refused to/i.test(msg.text())) violations.push(msg.text());
    });
    await page.route("**/*", async (route) => {
      if (route.request().resourceType() !== "document") return route.fallback();
      const response = await route.fetch();
      await route.fulfill({ response, headers: { ...response.headers(), "content-security-policy": csp! } });
    });
    await openScreen(page, screen);
    expect(violations).toEqual([]);
  });
}
