/**
 * Pré-visualização de exemplo para a vitrine do /demo (e para os testes de interface).
 * Dados inventados, no formato que a API devolve. Nenhuma chamada ao backend.
 */
import type { ImportBatch, ImportRow } from "@/data/api";

let seq = 0;
function row(partial: Partial<ImportRow> & Pick<ImportRow, "status">): ImportRow {
  seq += 1;
  return {
    id: `00000000-0000-4000-8000-${String(seq).padStart(12, "0")}`,
    line_numbers: [seq + 1],
    decision: partial.status === "ok" ? "import" : partial.status === "possible_duplicate" ? "keep_existing" : null,
    messages: [],
    raw: {},
    draft: null,
    match_movement_ids: [],
    movement_id: null,
    ...partial,
  };
}

const draft = (d: Partial<NonNullable<ImportRow["draft"]>> & Pick<NonNullable<ImportRow["draft"]>, "trade_date" | "type" | "asset_label">) => ({
  ticker: d.asset_label,
  broker_id: "xp",
  broker_name: "XP Investimentos",
  quantity: null,
  unit_price: null,
  fees: "0",
  amount: null,
  factor: null,
  income_kind: null,
  ...d,
});

const negociacao: ImportRow[] = [
  row({ status: "ok", draft: draft({ trade_date: "2026-09-02", type: "compra", asset_label: "WEGE3", quantity: "20", unit_price: "44.12" }) }),
  row({ status: "ok", draft: draft({ trade_date: "2026-09-02", type: "compra", asset_label: "HGLG11", quantity: "5", unit_price: "157.8", broker_id: "btg", broker_name: "BTG Pactual" }) }),
  row({
    status: "possible_duplicate",
    draft: draft({ trade_date: "2026-09-15", type: "compra", asset_label: "PETR4", quantity: "30", unit_price: "37.95" }),
    messages: [{ level: "warning", text: "Parece a mesma operação já lançada por Manual em 15/09/2026." }],
    match_movement_ids: ["10000000-0000-4000-8000-000000000001"],
  }),
  row({ status: "already_imported", draft: draft({ trade_date: "2026-08-20", type: "venda", asset_label: "BBAS3", quantity: "40", unit_price: "21.4" }), messages: [{ level: "info", text: "Já importada antes." }] }),
  row({ status: "ok", draft: draft({ trade_date: "2026-09-22", type: "venda", asset_label: "ITUB4", quantity: "15", unit_price: "39.6" }) }),
];

const movimentacao: ImportRow[] = [
  row({ status: "ok", draft: draft({ trade_date: "2026-09-12", type: "provento", asset_label: "HGLG11", amount: "6.5", income_kind: "rendimento", broker_id: "btg", broker_name: "BTG Pactual" }) }),
  row({ status: "ok", draft: draft({ trade_date: "2026-09-29", type: "provento", asset_label: "TAEE11", amount: "48.3", income_kind: "dividendo" }) }),
  row({
    status: "ignored",
    raw: { movimentacao: "Transferência - Liquidação", produto: "WEGE3" },
    messages: [{ level: "info", text: "Liquidação de uma compra ou venda: a operação vem do export de Negociação." }],
  }),
  row({
    status: "error",
    raw: { movimentacao: "Rendimento", produto: "XYZW11" },
    messages: [{ level: "error", text: "Ativo não encontrado: XYZW11." }],
  }),
];

export const SAMPLE_BATCH: ImportBatch = {
  id: "00000000-0000-4000-8000-0000000000b1",
  status: "preview",
  created_at: "2026-10-28T22:40:00Z",
  finished_at: null,
  warnings: [],
  files: [
    { id: "00000000-0000-4000-8000-0000000000f1", label: "B3 · Negociação, 08/2026 a 09/2026", adapter: "b3-negociacao", rows: negociacao, counts: countOf(negociacao) },
    { id: "00000000-0000-4000-8000-0000000000f2", label: "B3 · Movimentação, 09/2026 a 09/2026", adapter: "b3-movimentacao", rows: movimentacao, counts: countOf(movimentacao) },
  ],
  counts: countOf([...negociacao, ...movimentacao]),
};

export const SAMPLE_FILENAMES = ["negociacao-2026-10-28.xlsx", "movimentacao-2026-10-28.xlsx"];

function countOf(rows: ImportRow[]): ImportBatch["counts"] {
  const out: ImportBatch["counts"] = {};
  for (const r of rows) out[r.status] = (out[r.status] ?? 0) + 1;
  return out;
}
