/**
 * Backend simulado para os testes de interface: responde as chamadas do PostgREST com as
 * fixtures do demo (e2e/fixtures), aplicando o pedaço da sintaxe de filtros que as telas
 * usam. Com CAURI_E2E_LIVE=1, nada é simulado e os testes batem no Supabase local.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import type { Page, Route } from "@playwright/test";

export const LIVE = process.env.CAURI_E2E_LIVE === "1";

type Row = Record<string, unknown>;

const FIXTURES = path.resolve("e2e/fixtures/demo");
const cache = new Map<string, Row[]>();

export function fixture(view: string): Row[] {
  let rows = cache.get(view);
  if (!rows) {
    rows = JSON.parse(readFileSync(path.join(FIXTURES, `${view}.json`), "utf-8")) as Row[];
    cache.set(view, rows);
  }
  return rows;
}

function compare(a: unknown, b: unknown): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return -1;
  if (b === null || b === undefined) return 1;
  return String(a).localeCompare(String(b), "en", { numeric: true });
}

/** Subconjunto do PostgREST: eq, neq, lte, gte, lt, gt, is.null, ilike, order, limit, offset. */
export function applyQuery(rows: Row[], params: URLSearchParams): Row[] {
  let out = [...rows];
  for (const [key, raw] of params) {
    if (["select", "order", "limit", "offset", "or"].includes(key)) continue;
    const [op, ...rest] = raw.split(".");
    const value = rest.join(".");
    out = out.filter((row) => {
      const cell = row[key];
      switch (op) {
        case "eq": return String(cell) === value;
        case "neq": return String(cell) !== value;
        case "lte": return compare(cell, value) <= 0;
        case "gte": return compare(cell, value) >= 0;
        case "lt": return compare(cell, value) < 0;
        case "gt": return compare(cell, value) > 0;
        case "is": return value === "null" ? cell === null : cell !== null;
        case "ilike": return String(cell ?? "").toLowerCase().includes(value.replace(/\*/g, "").toLowerCase());
        case "in": return value.replace(/[()]/g, "").split(",").includes(String(cell));
        default: return true;
      }
    });
  }
  const order = params.get("order");
  if (order) {
    const keys = order.split(",").map((part) => {
      const [column, direction] = part.split(".");
      return { column: column ?? "", desc: direction === "desc" };
    });
    out.sort((a, b) => {
      for (const { column, desc } of keys) {
        const c = compare(a[column], b[column]);
        if (c) return desc ? -c : c;
      }
      return 0;
    });
  }
  const offset = Number(params.get("offset") ?? 0);
  const limit = params.get("limit");
  return out.slice(offset, limit ? offset + Number(limit) : undefined);
}

async function fulfillView(route: Route, rows: Row[]) {
  const url = new URL(route.request().url());
  const all = applyQuery(rows, new URLSearchParams([...url.searchParams].filter(([k]) => !["limit", "offset"].includes(k))));
  const page = applyQuery(rows, url.searchParams);
  const offset = Number(url.searchParams.get("offset") ?? 0);
  const headers: Record<string, string> = { "content-type": "application/json" };
  if ((route.request().headers()["prefer"] ?? "").includes("count=exact")) {
    headers["content-range"] = `${offset}-${offset + Math.max(page.length - 1, 0)}/${all.length}`;
  }
  await route.fulfill({ status: 200, headers, body: JSON.stringify(page) });
}

/** /demo: o anon vê a carteira demo das fixtures. */
export async function mockDemo(page: Page): Promise<void> {
  if (LIVE) return;
  await page.route(/\/rest\/v1\/([a-z_]+)/, async (route) => {
    const view = new URL(route.request().url()).pathname.split("/").pop() ?? "";
    await fulfillView(route, fixture(view));
  });
}
