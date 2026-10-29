/** Decisões sobre as linhas da pré-visualização e quantas movimentações elas geram. */
import type { ImportBatch, ImportDecision } from "@/data/api";

export function initialDecisions(batch: ImportBatch): Record<string, ImportDecision> {
  const out: Record<string, ImportDecision> = {};
  for (const f of batch.files) for (const r of f.rows) if (r.status === "possible_duplicate") out[r.id] = r.decision ?? "keep_existing";
  return out;
}

export function countToImport(batch: ImportBatch, decisions: Record<string, ImportDecision>): number {
  let n = 0;
  for (const f of batch.files)
    for (const r of f.rows) {
      if (r.status === "ok") n += 1;
      if (r.status === "possible_duplicate" && (decisions[r.id] ?? "keep_existing") !== "keep_existing") n += 1;
    }
  return n;
}
