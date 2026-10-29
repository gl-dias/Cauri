/**
 * Indicadores por período a partir da série diária que o engine grava. Aqui só há razões
 * entre números já calculados no backend (cota, CDI acumulado, linha do CDI): nenhuma
 * regra de negócio mora no front.
 */
import type { PortfolioDay } from "./types";

export type Period = "mes" | "6m" | "ano" | "tudo";

export const PERIODS: { key: Period; label: string }[] = [
  { key: "mes", label: "Mês" },
  { key: "6m", label: "6M" },
  { key: "ano", label: "Ano" },
  { key: "tudo", label: "Tudo" },
];

function shiftMonths(iso: string, months: number): string {
  const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
  const index = y * 12 + (m - 1) + months;
  const year = Math.floor(index / 12);
  const month = (index % 12) + 1;
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${year}-${String(month).padStart(2, "0")}-${String(Math.min(d, last)).padStart(2, "0")}`;
}

/** Último dia antes do período (a "base") e os dias do período. Base nula = desde o início. */
export function slicePeriod(days: PortfolioDay[], period: Period): { base: PortfolioDay | null; rows: PortfolioDay[] } {
  const last = days.at(-1);
  if (!last || period === "tudo") return { base: null, rows: days };
  let cutoff: string; // a base é o último dia com data < cutoff
  if (period === "mes") cutoff = `${last.snap_date.slice(0, 7)}-01`;
  else if (period === "ano") cutoff = `${last.snap_date.slice(0, 4)}-01-01`;
  else cutoff = shiftMonths(last.snap_date, -6);
  const index = days.findIndex((d) => d.snap_date >= cutoff);
  if (index <= 0) return { base: null, rows: days }; // carteira começou dentro do período
  return { base: days[index - 1] ?? null, rows: days.slice(index) };
}

export type Kpis = {
  marketValue: number;
  marketValueChange: number | null; // variação do patrimônio (inclui aportes); nulo desde o início
  twr: number; // rentabilidade pelo método de cotas
  result: number; // resultado em R$ (patrimônio final - inicial - aportes líquidos)
  cdi: number;
  vsCdi: number; // diferença em pontos (0,01 = 1 p.p.)
  income: number;
  incomeCount: number;
  since: string;
  spark: { marketValue: number[]; twr: number[]; vsCdi: number[]; income: number[] };
};

function sample(values: number[], max = 48): number[] {
  if (values.length <= max) return values;
  const step = (values.length - 1) / (max - 1);
  return Array.from({ length: max }, (_, i) => values[Math.round(i * step)] ?? 0);
}

export function computeKpis(days: PortfolioDay[], period: Period): Kpis | null {
  const { base, rows } = slicePeriod(days, period);
  const last = rows.at(-1);
  const first = rows[0];
  if (!last || !first) return null;
  const q0 = base?.quota_value ?? 1;
  const c0 = base?.cdi_index ?? 1;
  const v0 = base?.market_value ?? 0;
  const flows = rows.reduce((sum, d) => sum + d.net_flows, 0);
  const twr = last.quota_value / q0 - 1;
  const cdi = last.cdi_index / c0 - 1;
  let cumulative = 0;
  return {
    marketValue: last.market_value,
    marketValueChange: base && v0 > 0 ? last.market_value / v0 - 1 : null,
    twr,
    result: last.market_value - v0 - flows,
    cdi,
    vsCdi: twr - cdi,
    income: rows.reduce((sum, d) => sum + d.income, 0),
    incomeCount: rows.filter((d) => d.income > 0).length,
    since: (base ?? first).snap_date,
    spark: {
      marketValue: sample(rows.map((d) => d.market_value)),
      twr: sample(rows.map((d) => d.quota_value / q0 - 1)),
      vsCdi: sample(rows.map((d) => d.quota_value / q0 / (d.cdi_index / c0) - 1)),
      income: sample(rows.map((d) => (cumulative += d.income))),
    },
  };
}

export type EvolutionPoint = {
  key: string;
  date: string;
  marketValue: number;
  cdiEquivalent: number | null;
  current: boolean;
};

/** Barras do gráfico: diárias no período "Mês", mensais (último dia do mês) nos outros. */
export function evolution(days: PortfolioDay[], period: Period): EvolutionPoint[] {
  const { rows } = slicePeriod(days, period);
  let points: PortfolioDay[];
  if (period === "mes") {
    points = rows;
  } else {
    const byMonth = new Map<string, PortfolioDay>();
    for (const d of rows) byMonth.set(d.snap_date.slice(0, 7), d);
    points = [...byMonth.values()];
  }
  return points.map((d, i) => ({
    key: d.snap_date,
    date: d.snap_date,
    marketValue: d.market_value,
    cdiEquivalent: d.cdi_equivalent,
    current: i === points.length - 1,
  }));
}
