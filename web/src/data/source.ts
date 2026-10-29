/**
 * Fonte de dados das telas. O /demo e o /app usam a mesma interface de leitura; só o
 * /app ganha escrita (Fase 3b). O DemoSource não tem nenhum método de escrita, e isso
 * é garantido pelo tipo: não há como uma tela do demo chamar uma gravação.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/** Cliente apontado para o schema marts (o único exposto pelo PostgREST). */
export type MartsClient = SupabaseClient<any, "marts", "marts">;

import type { AgendaItem, Bucket, Goal, Me, MovementRow, PortfolioDay, Position } from "./types";

export interface PortfolioReader {
  readonly mode: "demo" | "app";
  me(): Promise<Me>;
  portfolioDaily(): Promise<PortfolioDay[]>;
  positions(): Promise<Position[]>;
  buckets(day: string, kind: Bucket["bucket_kind"]): Promise<Bucket[]>;
  agenda(): Promise<AgendaItem[]>;
  recentMovements(limit: number, until: string): Promise<MovementRow[]>;
  goal(): Promise<Goal | null>;
}

export type DemoSource = PortfolioReader & { readonly mode: "demo" };

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

async function rows<T>(query: PromiseLike<{ data: T[] | null; error: { message: string } | null }>): Promise<T[]> {
  const { data, error } = await query;
  if (error) throw new Error(error.message);
  return data ?? [];
}

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
          .select(
            "id, trade_date, type, income_kind, asset_class, asset_label, quantity, unit_price, amount, factor, broker_name, origin, origin_label, voided_at",
          )
          .is("voided_at", null)
          .lte("trade_date", until)
          .order("trade_date", { ascending: false })
          .order("created_at", { ascending: false })
          .limit(limit),
      ),
    async goal() {
      const [goal] = await rows<Goal>(client.from("goal").select("target_amount, target_date").limit(1));
      return goal ?? null;
    },
  };
}

export function createDemoSource(client: MartsClient = createDemoClient()): DemoSource {
  return reader(client, "demo") as DemoSource;
}
