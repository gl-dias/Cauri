import { expect, type Page } from "@playwright/test";

import { SAMPLE_FILENAMES } from "../src/features/import/sample";
import { mockApp, mockDemo, mockLogin } from "./mocks";

export type Screen = {
  name: string;
  path: string;
  /** Texto que só aparece quando a tela terminou de carregar. */
  ready: string;
  setup: (page: Page) => Promise<void>;
  /** Interação depois de carregar (abrir uma classe, um diálogo...). */
  after?: (page: Page) => Promise<void>;
};

export const SCREENS: Screen[] = [
  { name: "demo-inicio", path: "/demo", ready: "Patrimônio total", setup: mockDemo },
  {
    name: "demo-carteira",
    path: "/demo/carteira",
    ready: "Posição no fechamento",
    setup: mockDemo,
    after: async (page) => {
      await page.getByRole("radio", { name: "Ações" }).click();
      await expect(page.getByRole("heading", { name: "Ações" })).toBeVisible();
    },
  },
  { name: "demo-lancamentos", path: "/demo/lancamentos", ready: "movimentações", setup: mockDemo },
  { name: "login", path: "/login", ready: "Enviar link de acesso", setup: mockLogin },
  { name: "app-inicio", path: "/app", ready: "Patrimônio total", setup: (page) => mockApp(page) },
  { name: "app-carteira", path: "/app/carteira", ready: "Posição no fechamento", setup: (page) => mockApp(page) },
  { name: "app-lancamentos", path: "/app/lancamentos", ready: "Novo lançamento", setup: (page) => mockApp(page) },
  {
    name: "app-novo-lancamento",
    path: "/app/lancamentos",
    ready: "Novo lançamento",
    setup: (page) => mockApp(page),
    after: async (page) => {
      await page.getByRole("button", { name: "Novo lançamento" }).click();
      const dialog = page.getByRole("dialog", { name: "Novo lançamento" });
      await dialog.getByLabel("Ativo").fill("PETR4");
      await dialog.getByLabel("Corretora").selectOption({ label: "XP Investimentos" });
      await dialog.getByLabel("Quantidade").fill("10");
      await dialog.getByLabel("Preço unitário (R$)").fill("38,45");
      await dialog.getByRole("button", { name: "Conferir" }).click();
      await expect(dialog.getByText("Tudo certo para gravar.")).toBeVisible();
    },
  },
  { name: "app-admin", path: "/app/admin", ready: "Convidados", setup: (page) => mockApp(page) },
  { name: "demo-importar", path: "/demo/importar", ready: "Exemplo de pré-visualização", setup: mockDemo },
  { name: "app-importar", path: "/app/importar", ready: "Arraste os arquivos aqui", setup: (page) => mockApp(page) },
  {
    name: "app-importar-previa",
    path: "/app/importar",
    ready: "Arraste os arquivos aqui",
    setup: (page) => mockApp(page),
    after: async (page) => {
      await page.getByLabel("Escolher arquivos").setInputFiles(
        SAMPLE_FILENAMES.map((name) => ({ name, mimeType: "application/octet-stream", buffer: Buffer.from("fictício") })),
      );
      await page.getByRole("button", { name: "Pré-visualizar" }).click();
      await expect(page.getByRole("button", { name: "Importar 5" })).toBeVisible();
    },
  },
];

export async function openScreen(page: Page, screen: Screen): Promise<void> {
  await screen.setup(page);
  await page.goto(screen.path);
  await expect(page.getByText(screen.ready).first()).toBeVisible();
  await page.waitForLoadState("networkidle");
  if (screen.after) await screen.after(page);
  await page.waitForTimeout(700); // foto de fundo, gráficos, animação dos diálogos
  // Sem rolagem horizontal em nenhuma largura.
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "rolagem horizontal").toBeLessThanOrEqual(0);
}
