import { defineConfig } from "@playwright/test";

// Testes de interface: contraste AA, ausência de rolagem horizontal e screenshots.
// Por padrão o backend é simulado (e2e/mocks.ts, fixtures do demo); com CAURI_E2E_LIVE=1
// os testes batem no Supabase local. No CI, o Playwright sobe o build com `vite preview`;
// localmente reaproveita o `npm run dev` se estiver no ar.
const CI = Boolean(process.env.CI);
const port = CI ? 4173 : 5173;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  reporter: "list",
  use: {
    baseURL: process.env.CAURI_WEB_URL ?? `http://127.0.0.1:${port}`,
    reducedMotion: "reduce", // captura o estado final, sem animação no meio
    colorScheme: "dark",
    locale: "pt-BR",
    timezoneId: "America/Sao_Paulo",
  },
  webServer: {
    command: CI ? "npx vite build && node scripts/pages-headers.mjs && npx vite preview --port 4173 --strictPort" : "npx vite --port 5173 --strictPort",
    url: `http://127.0.0.1:${port}/demo`,
    reuseExistingServer: !CI,
    timeout: 120_000,
    env: {
      VITE_SUPABASE_URL: process.env.VITE_SUPABASE_URL ?? "http://127.0.0.1:54321",
      VITE_SUPABASE_PUBLISHABLE_KEY: process.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? "sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH",
      VITE_API_URL: process.env.VITE_API_URL ?? "http://127.0.0.1:8000",
    },
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 } },
    {
      name: "celular",
      use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
    },
  ],
});
