/**
 * Backend simulado para os testes de interface: responde as chamadas do PostgREST com as
 * fixtures do demo (e2e/fixtures), aplicando o pedaço da sintaxe de filtros que as telas
 * usam. Com CAURI_E2E_LIVE=1, nada é simulado e os testes batem no Supabase local.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import type { Page, Route } from "@playwright/test";

import { SAMPLE_CONVERSATION, SAMPLE_CONVERSATIONS } from "../src/features/assistant/sample";
import { SAMPLE_BATCH, SAMPLE_SHORTFALL_BATCH } from "../src/features/import/sample";

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
  // Resposta de outra origem: o navegador só deixa o JS ler o Content-Range se ele for
  // exposto (o PostgREST de verdade faz isso).
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "access-control-allow-origin": "*",
    "access-control-expose-headers": "content-range",
  };
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

/* /app ------------------------------------------------------------------------------- */

const APP_USER = {
  id: "00000000-0000-4000-8000-0000000000aa",
  aud: "authenticated",
  role: "authenticated",
  email: "convidada@example.com",
  app_metadata: { provider: "email" },
  user_metadata: {},
};

function fakeJwt(): string {
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const exp = Math.floor(Date.now() / 1000) + 3600 * 24;
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: APP_USER.id, email: APP_USER.email, role: "authenticated", aud: "authenticated", exp })}.assinatura-falsa`;
}

const ALLOWLIST = [
  { email: "convidada@example.com", role: "admin", note: "dona da carteira", added_at: "2026-10-01T12:00:00Z" },
  { email: "amigo.um@example.com", role: "user", note: null, added_at: "2026-10-05T15:30:00Z" },
  { email: "amiga.dois@example.com", role: "user", note: "convidada em outubro", added_at: "2026-10-20T19:10:00Z" },
];

const JOB_RUNS = [
  { id: "r3", job: "daily", trigger: "cron", started_at: "2026-10-28T22:31:12Z", finished_at: "2026-10-28T22:32:40Z", status: "ok", details: {} },
  { id: "r2", job: "daily", trigger: "cron", started_at: "2026-10-28T21:33:05Z", finished_at: "2026-10-28T21:35:51Z", status: "partial", details: {} },
  { id: "r1", job: "backfill", trigger: "manual", started_at: "2026-10-27T13:02:44Z", finished_at: "2026-10-27T13:04:10Z", status: "ok", details: {} },
];
const JOB_SOURCES = [
  ...["brapi", "coingecko", "tesouro", "bcb_sgs"].map((source) => ({ run_id: "r3", source, status: source === "brapi" ? "ok" : "skipped", requested: 10, succeeded: 10, failed: 0, error_sample: null, duration_ms: 900 })),
  { run_id: "r2", source: "brapi", status: "partial", requested: 10, succeeded: 8, failed: 0, error_sample: "fechamento ainda não disponível: HGLG11, MXRF11", duration_ms: 2400 },
  { run_id: "r2", source: "coingecko", status: "ok", requested: 3, succeeded: 3, failed: 0, error_sample: null, duration_ms: 600 },
  { run_id: "r2", source: "tesouro", status: "ok", requested: 2, succeeded: 2, failed: 0, error_sample: null, duration_ms: 3100 },
  { run_id: "r2", source: "bcb_sgs", status: "ok", requested: 4, succeeded: 4, failed: 0, error_sample: null, duration_ms: 1200 },
  ...["cotahist", "tesouro", "coingecko", "bcb_sgs", "calendar"].map((source) => ({ run_id: "r1", source, status: "ok", requested: 1, succeeded: 1, failed: 0, error_sample: null, duration_ms: 5000 })),
];

const UNKNOWN_COLUMNS = ["Data Operação", "Operação", "Papel", "Qtde", "Preço", "Valor Total", "Corretagem"];
const PROFILES = [
  { id: "p-1", name: "Corretora Fictícia", mapping: { data: "Data", tipo: "Operação", ativo: "Papel", quantidade: "Qtde" }, options: { broker_id: "xp" }, created_at: "2026-10-10T12:00:00Z", last_used_at: "2026-10-20T21:10:00Z" },
];
const RECENT_IMPORTS = [
  { id: "r-imp-1", status: "committed", created_at: "2026-10-20T21:10:00Z", finished_at: "2026-10-20T21:11:00Z", labels: ["Template do Cauri, 01/2026 a 09/2026"], imported: 42 },
];

/** /app: sessão de uma convidada fictícia (admin), carteira = fixtures do demo, API simulada. */
export async function mockApp(page: Page, { role = "admin" as "admin" | "user" } = {}): Promise<void> {
  if (LIVE) return;
  const token = fakeJwt();
  const session = {
    access_token: token,
    refresh_token: "refresh-falso",
    token_type: "bearer",
    expires_in: 86400,
    expires_at: Math.floor(Date.now() / 1000) + 86400,
    user: APP_USER,
  };
  await page.addInitScript((value) => window.localStorage.setItem("cauri-app", value), JSON.stringify(session));

  await page.route(/\/auth\/v1\//, async (route) => {
    const url = route.request().url();
    if (url.includes("/user")) return route.fulfill({ json: APP_USER });
    if (url.includes("/token")) return route.fulfill({ json: session });
    if (url.includes("/logout")) return route.fulfill({ status: 204, body: "" });
    return route.fulfill({ json: {} });
  });

  const views: Record<string, Row[]> = {
    me: [{ user_id: APP_USER.id, display_name: "Convidada Teste", role }],
    job_runs: JOB_RUNS,
    job_sources: JOB_SOURCES,
  };
  await page.route(/\/rest\/v1\/([a-z_]+)/, async (route) => {
    const view = new URL(route.request().url()).pathname.split("/").pop() ?? "";
    await fulfillView(route, views[view] ?? fixture(view));
  });

  await page.route(/:8000\/v1\//, async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path.endsWith("/admin/allowlist") && req.method() === "GET") return route.fulfill({ json: ALLOWLIST });
    if (path.endsWith("/v1/imports") && req.method() === "GET") return route.fulfill({ json: RECENT_IMPORTS });
    if (path.endsWith("/v1/imports/profiles") && req.method() === "GET") return route.fulfill({ json: PROFILES });
    if (path.endsWith("/v1/assistant/config")) return route.fulfill({ json: { llm: "anthropic", model: "claude-haiku-5-5", voice: "navegador" } });
    if (path.endsWith("/v1/assistant/conversations")) return route.fulfill({ json: SAMPLE_CONVERSATIONS });
    if (path.endsWith("/v1/assistant/messages") && req.method() === "POST") {
      const [ask, reply] = SAMPLE_CONVERSATION.messages.slice(-2);
      return route.fulfill({ status: 201, json: { conversation_id: SAMPLE_CONVERSATION.id, messages: [ask, reply] } });
    }
    if (path.endsWith("/v1/imports") && req.method() === "POST") {
      // Arquivo "desconhecido": a API devolve só os nomes das colunas, para o mapeamento.
      const body = req.postDataBuffer()?.toString("latin1") ?? "";
      if (body.includes("deposito-usdt")) {
        return route.fulfill({ status: 201, json: { batch: SAMPLE_SHORTFALL_BATCH, problems: [], file_indexes: [0, 1] } });
      }
      if (body.includes("desconhecida")) {
        return route.fulfill({ status: 201, json: { batch: null, problems: [{ index: 0, message: "Não reconheci o formato deste arquivo.", columns: UNKNOWN_COLUMNS }], file_indexes: [] } });
      }
      return route.fulfill({ status: 201, json: { batch: SAMPLE_BATCH, problems: [], file_indexes: [0, 1, 2] } });
    }
    if (path.endsWith("/commit")) {
      return route.fulfill({ json: { created: 8, already_imported: 0, replaced: 0, skipped: 1, snapshots_updated: true } });
    }
    if (path.endsWith("/movements/check")) {
      return route.fulfill({ json: { ok: true, checks: [{ index: 0, ok: true, errors: [], duplicates: [], already_posted: null }] } });
    }
    if (path.endsWith("/movements") && req.method() === "POST") {
      return route.fulfill({ status: 201, json: { created: ["novo"], already_posted: [], snapshots_updated: true } });
    }
    return route.fulfill({ status: 204, body: "" });
  });
}

/** Login: o envio do magic link sempre "dá certo" (a tela nunca revela a allowlist). */
export async function mockLogin(page: Page): Promise<void> {
  if (LIVE) return;
  await page.route(/\/auth\/v1\//, (route) => route.fulfill({ json: {} }));
}
