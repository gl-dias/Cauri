import { describe, expect, it } from "vitest";

import { computeKpis, evolution, slicePeriod } from "../metrics";
import type { PortfolioDay } from "../types";

function day(snap_date: string, market_value: number, quota_value: number, cdi_index: number, extra: Partial<PortfolioDay> = {}): PortfolioDay {
  return {
    snap_date, market_value, quota_value, cdi_index,
    cost_basis: 0, net_flows: 0, income: 0, ipca_index: 1, stale_count: 0, cdi_equivalent: market_value, ...extra,
  };
}

const DAYS: PortfolioDay[] = [
  day("2025-12-30", 1000, 1.0, 1.0, { net_flows: 1000 }),
  day("2026-01-30", 1100, 1.1, 1.01),
  day("2026-06-30", 2200, 1.155, 1.07, { net_flows: 1000 }),
  day("2026-09-30", 2310, 1.2128, 1.1, { income: 10 }),
  day("2026-10-15", 2300, 1.2075, 1.105),
  day("2026-10-28", 2420, 1.2705, 1.11),
];

describe("períodos", () => {
  it("mês: base é o último dia do mês anterior", () => {
    const { base, rows } = slicePeriod(DAYS, "mes");
    expect(base?.snap_date).toBe("2026-09-30");
    expect(rows.map((d) => d.snap_date)).toEqual(["2026-10-15", "2026-10-28"]);
  });

  it("ano: desde 1º de janeiro", () => {
    expect(slicePeriod(DAYS, "ano").base?.snap_date).toBe("2025-12-30");
  });

  it("6 meses: base é o último dia antes de 28/04", () => {
    expect(slicePeriod(DAYS, "6m").base?.snap_date).toBe("2026-01-30");
  });

  it("tudo: sem base", () => {
    expect(slicePeriod(DAYS, "tudo").base).toBeNull();
  });
});

describe("indicadores", () => {
  it("rentabilidade pela cota e diferença para o CDI no período", () => {
    const k = computeKpis(DAYS, "ano")!;
    expect(k.twr).toBeCloseTo(0.2705, 4);
    expect(k.cdi).toBeCloseTo(0.11, 4);
    expect(k.vsCdi).toBeCloseTo(0.1605, 4);
  });

  it("desde o início usa cota e CDI começando em 1", () => {
    const k = computeKpis(DAYS, "tudo")!;
    expect(k.twr).toBeCloseTo(0.2705, 4);
    expect(k.marketValueChange).toBeNull();
    expect(k.result).toBeCloseTo(2420 - 2000, 6);
  });

  it("resultado em reais desconta os aportes do período e soma proventos", () => {
    const k = computeKpis(DAYS, "6m")!;
    expect(k.result).toBeCloseTo(2420 - 1100 - 1000, 6);
    expect(k.income).toBe(10);
  });

  it("carteira negativa contra o CDI aparece negativa", () => {
    const k = computeKpis([day("2026-01-02", 100, 1, 1), day("2026-12-30", 111.7, 1.117, 1.143)], "tudo")!;
    expect(k.vsCdi).toBeLessThan(0);
  });
});

describe("evolução", () => {
  it("um ponto por mês fora do período Mês, com o último destacado", () => {
    const points = evolution(DAYS, "tudo");
    expect(points.map((p) => p.date)).toEqual(["2025-12-30", "2026-01-30", "2026-06-30", "2026-09-30", "2026-10-28"]);
    expect(points.filter((p) => p.current).map((p) => p.date)).toEqual(["2026-10-28"]);
  });

  it("um ponto por pregão no período Mês", () => {
    expect(evolution(DAYS, "mes").map((p) => p.date)).toEqual(["2026-10-15", "2026-10-28"]);
  });
});
