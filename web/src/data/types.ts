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

export type MovementRow = {
  id: string;
  trade_date: string;
  type: MovementType;
  income_kind: string | null;
  asset_class: AssetClassKey;
  asset_label: string;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
  factor: number | null;
  broker_name: string | null;
  origin: "import" | "manual" | "chat";
  origin_label: string | null;
  voided_at: string | null;
};

export type Goal = {
  target_amount: number;
  target_date: string | null;
};
