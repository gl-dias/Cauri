/** Linhas das views do schema marts (contrato de leitura do front). */
import type { AssetClassKey } from "@/theme/tokens";

export type Me = {
  user_id: string;
  display_name: string;
  role: "admin" | "user" | "demo";
};

export type PortfolioDay = {
  snap_date: string;
  market_value: number;
  cost_basis: number;
  net_flows: number;
  income: number;
  quota_value: number;
  cdi_index: number;
  ipca_index: number;
  stale_count: number;
  cdi_equivalent: number | null;
};

export type Bucket = {
  snap_date: string;
  bucket_kind: "class" | "broker";
  bucket_key: string;
  market_value: number;
  cost_basis: number;
  quota_value: number;
};

export type Position = {
  snap_date: string;
  asset_class: AssetClassKey;
  broker_id: string;
  broker_name: string | null;
  asset_id: string | null;
  instrument_id: string | null;
  label: string;
  name: string | null;
  fi_kind: "CDB" | "LCI" | "LCA" | null;
  fi_rate_pct: number | null;
  fi_maturity_date: string | null;
  quantity: number | null;
  avg_cost: number | null;
  cost_basis: number;
  price: number | null;
  price_date: string | null;
  price_status: "ok" | "stale" | "missing";
  market_value: number;
};

export type AgendaItem = {
  kind: "provento" | "vencimento";
  event_date: string;
  label: string;
  amount: number | null;
  detail: string | null;
  broker_id: string;
};

export type MovementType =
  | "compra"
  | "venda"
  | "aporte"
  | "resgate"
  | "provento"
  | "desdobramento"
  | "grupamento"
  | "bonificacao";

export type Origin = "import" | "manual" | "chat";

export type MovementRow = {
  id: string;
  trade_date: string;
  type: MovementType;
  income_kind: string | null;
  asset_class: AssetClassKey;
  asset_id: string | null;
  instrument_id: string | null;
  asset_label: string;
  asset_name?: string | null;
  quantity: number | null;
  unit_price: number | null;
  fees?: number;
  amount: number | null;
  factor: number | null;
  fi_rate_pct?: number | null;
  fi_maturity_date?: string | null;
  broker_id?: string;
  broker_name: string | null;
  origin: Origin;
  origin_label: string | null;
  notes?: string | null;
  created_at?: string;
  voided_at: string | null;
  void_reason?: string | null;
  // Operação em outra moeda (cripto em USDT, BTC...): valor original e cotação usada.
  orig_currency?: string | null;
  orig_value?: number | null;
  fx_rate?: number | null;
  fx_date?: string | null;
  fx_source?: "ptax" | "fechamento" | null;
  fee_asset?: string | null;
  fee_quantity?: number | null;
  opening_balance?: boolean;
};

export type LedgerFilter = {
  search?: string;
  type?: MovementType;
  assetClass?: AssetClassKey;
  origin?: Origin;
  showVoided?: boolean;
};

export type Paged<T> = { rows: T[]; total: number };

export type Asset = {
  id: string;
  ticker: string;
  name: string;
  class: AssetClassKey;
  issuer_code: string | null;
  maturity_date: string | null;
};

export type Broker = { id: string; name: string; kind: "corretora" | "banco" | "exchange" };

export type FiInstrument = {
  id: string;
  kind: "CDB" | "LCI" | "LCA";
  issuer_name: string;
  rate_pct: number;
  maturity_date: string;
  broker_id: string;
  label: string;
};

export type JobRun = {
  id: string;
  job: string;
  trigger: "cron" | "manual";
  started_at: string;
  finished_at: string | null;
  status: "running" | "ok" | "partial" | "failed";
  details: Record<string, unknown>;
};

export type JobSource = {
  run_id: string;
  source: string;
  status: "ok" | "partial" | "failed" | "quota_exceeded" | "skipped";
  requested: number;
  succeeded: number;
  failed: number;
  error_sample: string | null;
  duration_ms: number | null;
};

export type Goal = {
  target_amount: number;
  target_date: string | null;
};
