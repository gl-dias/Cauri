/**
 * Fonte de dados das telas. O /demo e o /app usam a mesma interface de leitura; só o
 * /app ganha escrita (a API). O DemoSource não tem nenhum método de escrita, e isso é
 * garantido pelo tipo: não há como uma tela do demo chamar uma gravação.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import type { ApiClient } from "./api";
import type {
  AgendaItem,
  Asset,
  Broker,
  Bucket,
  FiInstrument,
  Goal,
  JobRun,
  JobSource,
  LlmUsageDay,
  LlmUsageUser,
  LedgerFilter,
  Me,
  MovementRow,
  Paged,
  PortfolioDay,
  Position,
} from "./types";

/** Cliente apontado para o schema marts (o único exposto pelo PostgREST). */
export type MartsClient = SupabaseClient<any, "marts", "marts">;

export interface PortfolioReader {
  readonly mode: "demo" | "app";
  me(): Promise<Me>;
  portfolioDaily(): Promise<PortfolioDay[]>;
  positions(): Promise<Position[]>;
  buckets(day: string, kind: Bucket["bucket_kind"]): Promise<Bucket[]>;
  agenda(): Promise<AgendaItem[]>;
  recentMovements(limit: number, until: string): Promise<MovementRow[]>;
  movements(filter: LedgerFilter, offset: number, limit: number): Promise<Paged<MovementRow>>;
  goal(): Promise<Goal | null>;
}

export type DemoSource = PortfolioReader & { readonly mode: "demo" };

/** O /app lê pelo Supabase (RLS) e escreve pela API Python. */
export type AppSource = PortfolioReader & {
  readonly mode: "app";
  readonly api: ApiClient;
  searchAssets(term: string): Promise<Asset[]>;
  brokers(): Promise<Broker[]>;
  fiInstruments(): Promise<FiInstrument[]>;
  jobRuns(limit: number): Promise<JobRun[]>;
  jobSources(runIds: string[]): Promise<JobSource[]>;
  llmUsageDaily(): Promise<LlmUsageDay[]>;
  llmUsageUsers(): Promise<LlmUsageUser[]>;
};

export type AnySource = DemoSource | AppSource;

function env(name: "VITE_SUPABASE_URL" | "VITE_SUPABASE_PUBLISHABLE_KEY"): string {
  const value = import.meta.env[name] as string | undefined;
  if (!value) throw new Error(`variável ${name} não definida (veja o .env.example)`);
  return value;
}

/**
 * Cliente do /demo: chave pública, nenhuma sessão, armazenamento próprio. Mesmo com alguém
 * logado no /app no mesmo navegador, este cliente nunca envia o JWT; o banco o trata como
 * anon e o RLS só devolve a carteira demo.
 */
export function createDemoClient(): MartsClient {
  return createClient<any, "marts">(env("VITE_SUPABASE_URL"), env("VITE_SUPABASE_PUBLISHABLE_KEY"), {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false, storageKey: "cauri-demo" },
    db: { schema: "marts" },
  });
}

/** Cliente do /app: sessão do magic link (verifyOtp em /entrar) guardada no navegador. */
export function createAppClient(): MartsClient {
  return createClient<any, "marts">(env("VITE_SUPABASE_URL"), env("VITE_SUPABASE_PUBLISHABLE_KEY"), {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: "pkce", storageKey: "cauri-app" },
    db: { schema: "marts" },
  });
}

type Result<T> = { data: T[] | null; error: { message: string } | null; count?: number | null };

async function rows<T>(query: PromiseLike<Result<T>>): Promise<T[]> {
  const { data, error } = await query;
  if (error) throw new Error(error.message);
  return data ?? [];
}

const MOVEMENT_COLUMNS =
  "id, trade_date, type, income_kind, asset_class, asset_id, instrument_id, asset_label, asset_name, quantity, unit_price, fees, amount, factor, fi_rate_pct, fi_maturity_date, broker_id, broker_name, origin, origin_label, notes, created_at, voided_at, void_reason, orig_currency, orig_value, fx_rate, fx_date, fx_source, fee_asset, fee_quantity, opening_balance";

function reader(client: MartsClient, mode: "demo" | "app"): PortfolioReader {
  return {
    mode,
    async me() {
      const [me] = await rows<Me>(client.from("me").select("user_id, display_name, role").limit(1));
      if (!me) throw new Error("perfil não encontrado");
      return me;
    },
    portfolioDaily: () =>
      rows<PortfolioDay>(
        client
          .from("portfolio_daily")
          .select(
            "snap_date, market_value, cost_basis, net_flows, income, quota_value, cdi_index, ipca_index, stale_count, cdi_equivalent",
          )
          .order("snap_date"),
      ),
    positions: () =>
      rows<Position>(client.from("positions_current").select("*").order("market_value", { ascending: false })),
    buckets: (day, kind) =>
      rows<Bucket>(
        client
          .from("buckets_daily")
          .select("snap_date, bucket_kind, bucket_key, market_value, cost_basis, quota_value")
          .eq("snap_date", day)
          .eq("bucket_kind", kind),
      ),
    agenda: () => rows<AgendaItem>(client.from("agenda").select("*").order("event_date")),
    recentMovements: (limit, until) =>
      rows<MovementRow>(
        client
          .from("movements")
          .select(MOVEMENT_COLUMNS)
          .is("voided_at", null)
          .lte("trade_date", until)
          .order("trade_date", { ascending: false })
          .order("created_at", { ascending: false })
          .limit(limit),
      ),
    async movements(filter, offset, limit) {
      let query = client.from("movements").select(MOVEMENT_COLUMNS, { count: "exact" });
      if (!filter.showVoided) query = query.is("voided_at", null);
      if (filter.type) query = query.eq("type", filter.type);
      if (filter.assetClass) query = query.eq("asset_class", filter.assetClass);
      if (filter.origin) query = query.eq("origin", filter.origin);
      const term = filter.search?.trim().replace(/[%*,()]/g, "");
      if (term) query = query.ilike("asset_label", `*${term}*`);
      const { data, error, count } = await query
        .order("trade_date", { ascending: false })
        .order("created_at", { ascending: false })
        .range(offset, offset + limit - 1);
      if (error) throw new Error(error.message);
      return { rows: (data ?? []) as MovementRow[], total: count ?? 0 };
    },
    async goal() {
      const [goal] = await rows<Goal>(client.from("goal").select("target_amount, target_date").limit(1));
      return goal ?? null;
    },
  };
}

export function createDemoSource(client: MartsClient = createDemoClient()): DemoSource {
  return reader(client, "demo") as DemoSource;
}

export function createAppSource(client: MartsClient, api: ApiClient): AppSource {
  return {
    ...reader(client, "app"),
    mode: "app",
    api,
    searchAssets: (term) => {
      const clean = term.trim().replace(/[%*,()]/g, "");
      return rows<Asset>(
        client
          .from("assets")
          .select("id, ticker, name, class, issuer_code, maturity_date")
          .or(`ticker.ilike.*${clean}*,name.ilike.*${clean}*`)
          .order("ticker")
          .limit(12),
      );
    },
    brokers: () => rows<Broker>(client.from("brokers").select("id, name, kind").order("name")),
    fiInstruments: () => rows<FiInstrument>(client.from("fi_instruments").select("*").order("maturity_date")),
    jobRuns: (limit) =>
      rows<JobRun>(client.from("job_runs").select("*").order("started_at", { ascending: false }).limit(limit)),
    jobSources: (runIds) =>
      runIds.length ? rows<JobSource>(client.from("job_sources").select("*").in("run_id", runIds)) : Promise.resolve([]),
    llmUsageDaily: () => rows<LlmUsageDay>(client.from("llm_usage_daily").select("*").order("day", { ascending: false })),
    llmUsageUsers: () => rows<LlmUsageUser>(client.from("llm_usage_users").select("*").order("tokens", { ascending: false })),
  };
}
