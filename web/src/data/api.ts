/**
 * Cliente da API de escrita (FastAPI). Toda gravação passa por aqui, sempre com o JWT da
 * sessão; números trafegam como texto para nunca passarem por float.
 */
import type { MovementType } from "./types";

export type ManualEntry = {
  client_key: string;
  type: MovementType;
  trade_date: string;
  broker_id: string;
  ticker?: string;
  quantity?: string;
  unit_price?: string;
  fees?: string;
  amount?: string;
  factor?: string;
  income_kind?: "dividendo" | "jcp" | "rendimento" | "juros";
  instrument_id?: string;
  fi_kind?: "CDB" | "LCI" | "LCA";
  fi_issuer?: string;
  fi_rate_pct?: string;
  fi_maturity?: string;
  notes?: string;
  opening_balance?: boolean;
};

export type MovementPatch = Partial<
  Pick<ManualEntry, "trade_date" | "ticker" | "broker_id" | "quantity" | "unit_price" | "fees" | "amount" | "factor" | "income_kind" | "notes">
> & { reason?: string };

export type CheckIssue = { code: string; message: string; field: string | null };
export type DraftCheck = {
  index: number;
  ok: boolean;
  errors: CheckIssue[];
  duplicates: { movement_id: string; origin: string; origin_label: string | null; trade_date: string }[];
  already_posted: string | null;
};
export type ChecksOut = { ok: boolean; checks: DraftCheck[] };
export type PostOut = { created: string[]; already_posted: string[]; snapshots_updated: boolean };
export type AllowlistEntry = { email: string; role: "admin" | "user"; note: string | null; added_at: string };

export type ImportDecision = "import" | "keep_existing" | "replace" | "import_new";
export type ImportRowStatus = "ok" | "error" | "already_imported" | "possible_duplicate" | "ignored";
export type ImportMessage = { level: "error" | "warning" | "info"; text: string };
export type ImportDraft = {
  trade_date: string;
  type: MovementType;
  ticker: string | null;
  asset_label: string;
  broker_id: string;
  broker_name: string;
  quantity: string | null;
  unit_price: string | null;
  fees: string | null;
  amount: string | null;
  factor: string | null;
  income_kind: "dividendo" | "jcp" | "rendimento" | "juros" | null;
  orig_currency?: string | null;
  orig_value?: string | null;
  fx_rate?: string | null;
  fx_date?: string | null;
  fx_source?: "ptax" | "fechamento" | null;
  fee_asset?: string | null;
  fee_quantity?: string | null;
  opening_balance?: boolean;
};
export type ImportRow = {
  id: string;
  line_numbers: number[];
  status: ImportRowStatus;
  decision: ImportDecision | null;
  messages: ImportMessage[];
  raw: Record<string, string>;
  draft: ImportDraft | null;
  match_movement_ids: string[];
  movement_id: string | null;
};
export type ImportFile = { id: string; label: string; adapter: string; rows: ImportRow[]; counts: Partial<Record<ImportRowStatus, number>> };
export type ImportBatch = {
  id: string;
  status: "preview" | "committed" | "discarded";
  created_at: string;
  finished_at: string | null;
  warnings: string[];
  files: ImportFile[];
  counts: Partial<Record<ImportRowStatus, number>>;
  suggestions?: OpeningSuggestion[];
};
/** Saldo que falta para uma venda descoberta, com a sugestão de saldo inicial. */
export type OpeningSuggestion = {
  ticker: string;
  broker_id: string;
  trade_date: string;
  quantity: string;
  first_shortfall: string;
  unit_cost: string | null;
  cost_note: string | null;
  deposit: { quantity: string; day: string } | null;
};
export type OpeningBalanceIn = { ticker: string; trade_date: string; quantity: string; unit_cost: string; broker_id: string };
export type ImportProblem = { index: number; message: string; columns?: string[] };
export type ImportPreview = { batch: ImportBatch | null; problems: ImportProblem[]; file_indexes: number[] };
export type ProfileField = "data" | "tipo" | "ativo" | "quantidade" | "preco" | "valor" | "taxa" | "ativo_taxa" | "moeda" | "corretora" | "obs";
export type ProfileOptions = { broker_id?: string; decimal?: "," | "."; date_format?: "dd/mm/aaaa" | "aaaa-mm-dd" | "mm/dd/aaaa"; currency?: string };
export type ImportProfile = {
  id: string;
  name: string;
  mapping: Partial<Record<ProfileField, string>>;
  options: ProfileOptions;
  created_at: string;
  last_used_at: string | null;
};
export type ImportSummary = { id: string; status: ImportBatch["status"]; created_at: string; finished_at: string | null; labels: string[]; imported: number };
export type ImportCommitOut = { created: number; already_imported: number; replaced: number; skipped: number; snapshots_updated: boolean };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body: { detail?: string; checks?: DraftCheck[]; issues?: CheckIssue[]; field?: string; messages?: string[] } = {},
  ) {
    super(message);
  }
}

export type ApiClient = ReturnType<typeof createApi>;

export function createApi(baseUrl: string, token: () => Promise<string | null>) {
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const jwt = await token();
    // FormData (envio de arquivos) leva o Content-Type com o boundary que o navegador gera.
    const isForm = body instanceof FormData;
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
      method,
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        ...(jwt ? { Authorization: `Bearer ${jwt}` } : {}),
      },
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    });
    if (response.status === 204) return undefined as T;
    const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    if (!response.ok) {
      const detail = typeof data.detail === "string" ? data.detail : "Não foi possível concluir. Tente de novo.";
      throw new ApiError(response.status, detail, data as ApiError["body"]);
    }
    return data as T;
  }

  return {
    checkManual: (entries: ManualEntry[]) => call<ChecksOut>("POST", "/v1/movements/check", { entries }),
    postManual: (entries: ManualEntry[]) => call<PostOut>("POST", "/v1/movements", { entries }),
    editMovement: (id: string, patch: MovementPatch) => call<void>("PATCH", `/v1/movements/${id}`, patch),
    voidMovement: (id: string, reason: string) => call<void>("POST", `/v1/movements/${id}/void`, { reason }),
    imports: {
      preview: (files: File[]) => {
        const form = new FormData();
        for (const file of files) form.append("files", file, file.name);
        return call<ImportPreview>("POST", "/v1/imports", form);
      },
      recent: () => call<ImportSummary[]>("GET", "/v1/imports"),
      get: (id: string) => call<ImportBatch>("GET", `/v1/imports/${id}`),
      commit: (id: string, decisions: Record<string, ImportDecision>) =>
        call<ImportCommitOut>("POST", `/v1/imports/${id}/commit`, { decisions }),
      discard: (id: string) => call<void>("POST", `/v1/imports/${id}/discard`),
      addOpening: (id: string, body: OpeningBalanceIn) => call<ImportBatch>("POST", `/v1/imports/${id}/opening-balances`, body),
      profiles: {
        list: () => call<ImportProfile[]>("GET", "/v1/imports/profiles"),
        save: (name: string, mapping: Partial<Record<ProfileField, string>>, options: ProfileOptions) =>
          call<ImportProfile>("POST", "/v1/imports/profiles", { name, mapping, options }),
        remove: (id: string) => call<void>("DELETE", `/v1/imports/profiles/${id}`),
      },
    },
    allowlist: {
      list: () => call<AllowlistEntry[]>("GET", "/v1/admin/allowlist"),
      add: (email: string, role: "admin" | "user", note?: string) =>
        call<AllowlistEntry>("POST", "/v1/admin/allowlist", { email, role, note: note || null }),
      update: (email: string, role: "admin" | "user") =>
        call<AllowlistEntry>("PATCH", `/v1/admin/allowlist/${encodeURIComponent(email)}`, { role }),
      remove: (email: string) => call<void>("DELETE", `/v1/admin/allowlist/${encodeURIComponent(email)}`),
    },
  };
}
