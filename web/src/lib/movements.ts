import type { MovementRow, MovementType, Origin } from "@/data/types";

import { formatBRL, formatQuantity } from "./format";

export const TYPE_LABEL: Record<MovementType, string> = {
  compra: "Compra",
  venda: "Venda",
  aporte: "Aporte",
  resgate: "Resgate",
  provento: "Provento",
  desdobramento: "Desdobramento",
  grupamento: "Grupamento",
  bonificacao: "Bonificação",
};

export const ORIGIN_LABEL: Record<Origin, string> = { import: "Planilha", manual: "Manual", chat: "Chat" };

/** "Saldo inicial" para a compra marcada; o rótulo do tipo nos outros casos. */
export function typeText(m: { type: MovementType; opening_balance?: boolean | null }): string {
  return m.opening_balance ? "Saldo inicial" : TYPE_LABEL[m.type];
}

export const INCOME_LABEL: Record<string, string> = {
  dividendo: "Dividendo",
  jcp: "JCP",
  rendimento: "Rendimento",
  juros: "Juros",
};

/** Texto da origem: "Planilha XP", "Manual", "Chat". */
export function originText(m: Pick<MovementRow, "origin" | "origin_label">): string {
  if (m.origin === "import") return m.origin_label ?? ORIGIN_LABEL.import;
  return ORIGIN_LABEL[m.origin];
}

/** Valor da movimentação em reais (quantidade x preço nas negociações). */
export function movementValue(m: MovementRow): number | null {
  if (m.amount !== null) return m.amount;
  if (m.quantity !== null && m.unit_price !== null) return m.quantity * m.unit_price;
  return null;
}

/** "Compra de 36", "Provento de R$ 64,78", "Desdobramento (fator 2)". */
export function describe(m: MovementRow): string {
  if (m.quantity !== null && (m.type === "compra" || m.type === "venda")) {
    return `${TYPE_LABEL[m.type]} de ${formatQuantity(m.quantity)}`;
  }
  if (m.factor !== null) return `${TYPE_LABEL[m.type]} (fator ${formatQuantity(m.factor)})`;
  if (m.amount !== null) return `${TYPE_LABEL[m.type]} de ${formatBRL(m.amount)}`;
  return TYPE_LABEL[m.type];
}

/** Sigla curta para o avatar do ativo. */
export function assetInitials(label: string): string {
  return label.replace(/^(CDB|LCI|LCA)\s.*/, "$1").replace(/^TD-.*/, "TD").slice(0, 4);
}

/** "200 USDT/un · PTAX de 02/03" ou "0,01 BTC · fechamento de 02/03"; vazio se foi em reais. */
export function originalText(m: {
  type: MovementType;
  orig_currency?: string | null;
  orig_value?: number | string | null;
  fx_date?: string | null;
  fx_source?: string | null;
}): string {
  if (!m.orig_currency || m.orig_value === null || m.orig_value === undefined || !m.fx_date) return "";
  const per = m.type === "compra" || m.type === "venda" ? "/un" : "";
  const source = m.fx_source === "ptax" ? "PTAX" : "fechamento";
  const [, month, day] = m.fx_date.split("-");
  return `${formatQuantity(Number(m.orig_value))} ${m.orig_currency}${per} · ${source} de ${day}/${month}`;
}
