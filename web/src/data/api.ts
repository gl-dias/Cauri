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

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body: { detail?: string; checks?: DraftCheck[]; issues?: CheckIssue[]; field?: string } = {},
  ) {
    super(message);
  }
}

export type ApiClient = ReturnType<typeof createApi>;

export function createApi(baseUrl: string, token: () => Promise<string | null>) {
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const jwt = await token();
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(jwt ? { Authorization: `Bearer ${jwt}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
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
