// Grava as respostas das views do demo (anon, Supabase local) como fixtures dos testes
// de interface. Assim os testes de contraste e layout rodam no CI sem banco.
// Os dados são da carteira demo: fictícios, com preços públicos de mercado.
//
// Uso: node scripts/capture-fixtures.mjs   (com o Supabase local e o seed do demo no ar)

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const URL_BASE = process.env.VITE_SUPABASE_URL ?? "http://127.0.0.1:54321";
const KEY = process.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? "sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH";
const OUT = path.resolve("e2e/fixtures/demo");

const VIEWS = {
  me: "select=user_id,display_name,role",
  portfolio_daily: "select=*&order=snap_date",
  positions_current: "select=*&order=market_value.desc",
  buckets_daily: "select=*&order=snap_date",
  agenda: "select=*&order=event_date",
  goal: "select=*",
  movements: "select=*&order=trade_date.desc,created_at.desc",
  assets: "select=*&order=ticker",
  brokers: "select=*&order=name",
  fi_instruments: "select=*",
};

await mkdir(OUT, { recursive: true });
for (const [view, query] of Object.entries(VIEWS)) {
  const res = await fetch(`${URL_BASE}/rest/v1/${view}?${query}`, {
    headers: { apikey: KEY, "Accept-Profile": "marts" },
  });
  if (!res.ok) throw new Error(`${view}: HTTP ${res.status}`);
  let rows = await res.json();
  // Só o último dia dos recortes por classe e corretora interessa às telas.
  if (view === "buckets_daily") {
    const last = rows.at(-1)?.snap_date;
    rows = rows.filter((r) => r.snap_date === last);
  }
  // Removidas: só algumas, para o filtro "mostrar removidas" ter o que mostrar.
  if (view === "movements") {
    rows = [...rows.filter((r) => !r.voided_at), ...rows.filter((r) => r.voided_at).slice(0, 3)];
  }
  // O user_id do demo muda a cada banco novo; nas fixtures fica um id fixo.
  rows = rows.map((r) => ("user_id" in r ? { ...r, user_id: "00000000-0000-4000-8000-0000000000dd" } : r));
  await writeFile(path.join(OUT, `${view}.json`), `${JSON.stringify(rows, null, 1)}\n`);
  console.log(`${view}: ${rows.length} linhas`);
}
