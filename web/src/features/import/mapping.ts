/**
 * Mapeamento de colunas de um arquivo desconhecido para os campos do Cauri. A sugestão
 * inicial vem dos nomes das colunas; o usuário confere e salva como perfil.
 */
import type { ProfileField } from "@/data/api";

export const FIELDS: { key: ProfileField; label: string; hint?: string; required?: boolean }[] = [
  { key: "data", label: "Data", required: true },
  { key: "tipo", label: "Tipo de operação", hint: "compra, venda, provento ou recompensa (aceita buy, sell, C, V)", required: true },
  { key: "ativo", label: "Ativo", hint: "ticker, título do Tesouro ou moeda", required: true },
  { key: "quantidade", label: "Quantidade" },
  { key: "preco", label: "Preço unitário" },
  { key: "valor", label: "Valor total", hint: "proventos; ou o total, se não houver preço" },
  { key: "taxa", label: "Taxa" },
  { key: "ativo_taxa", label: "Ativo da taxa", hint: "se a taxa for paga em outra moeda (BNB)" },
  { key: "moeda", label: "Moeda do preço", hint: "BRL, USD, USDT..." },
  { key: "corretora", label: "Corretora ou exchange", hint: "ou escolha uma corretora fixa abaixo" },
  { key: "obs", label: "Observação" },
];

const SYNONYMS: Record<ProfileField, string[]> = {
  data: ["data", "date", "data da operacao", "data operacao", "data do negocio", "dia"],
  tipo: ["tipo", "operacao", "side", "type", "natureza", "c/v", "compra/venda"],
  ativo: ["ativo", "papel", "ticker", "codigo", "coin", "produto", "asset", "titulo", "moeda negociada"],
  quantidade: ["quantidade", "qtde", "qtd", "quant", "amount", "executed"],
  preco: ["preco", "price", "preco unitario", "pu", "cotacao"],
  valor: ["valor", "total", "valor total", "valor da operacao", "valor liquido"],
  taxa: ["taxa", "taxas", "corretagem", "fee", "custos", "emolumentos"],
  ativo_taxa: ["ativo da taxa", "fee coin", "moeda da taxa", "fee asset"],
  moeda: ["moeda", "currency", "moeda do preco", "quote"],
  corretora: ["corretora", "instituicao", "exchange", "broker", "conta"],
  obs: ["obs", "observacao", "observacoes", "nota", "descricao"],
};

export function normalize(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

/** Primeira coluna com nome conhecido para cada campo; cada coluna serve a um campo só. */
export function guessMapping(columns: string[]): Partial<Record<ProfileField, string>> {
  const out: Partial<Record<ProfileField, string>> = {};
  const used = new Set<string>();
  for (const field of FIELDS) {
    const hit = columns.find((c) => !used.has(c) && SYNONYMS[field.key].includes(normalize(c)));
    if (hit) {
      out[field.key] = hit;
      used.add(hit);
    }
  }
  return out;
}

/** O que falta para salvar o perfil (vazio quando está pronto). */
export function missingForProfile(mapping: Partial<Record<ProfileField, string>>, brokerId: string, name: string): string[] {
  const missing: string[] = [];
  for (const f of FIELDS) if (f.required && !mapping[f.key]) missing.push(f.label);
  if (!mapping.quantidade && !mapping.valor) missing.push("Quantidade ou Valor total");
  if (!mapping.corretora && !brokerId) missing.push("Corretora (coluna ou fixa)");
  if (!name.trim()) missing.push("Nome do perfil");
  return missing;
}
