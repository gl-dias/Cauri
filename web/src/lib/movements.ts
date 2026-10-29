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
