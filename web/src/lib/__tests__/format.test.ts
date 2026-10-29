import { describe, expect, it } from "vitest";

import { formatBRL, formatBRLSigned, formatDate, formatPctSigned, formatPP, greeting } from "../format";

describe("formatação pt-BR", () => {
  it("reais com milhar e centavos", () => {
    expect(formatBRL(1234.56)).toBe("R$ 1.234,56");
    expect(formatBRL(-1234.5)).toBe("−R$ 1.234,50");
    expect(formatBRLSigned(11598.79)).toBe("+R$ 11.598,79");
  });

  it("percentual e pontos percentuais com sinal tipográfico", () => {
    expect(formatPctSigned(0.1172)).toBe("+11,7%");
    expect(formatPctSigned(-0.025)).toBe("−2,5%");
    expect(formatPP(-0.0254)).toBe("−2,5 p.p.");
    expect(formatPP(0)).toBe("0,0 p.p.");
  });

  it("data sem passar por fuso horário", () => {
    expect(formatDate("2026-10-28")).toBe("28/10/2026");
  });

  it("saudação pelo horário de Brasília", () => {
    expect(greeting(new Date("2026-10-29T12:00:00Z"))).toBe("Bom dia"); // 9h
    expect(greeting(new Date("2026-10-29T18:00:00Z"))).toBe("Boa tarde"); // 15h
    expect(greeting(new Date("2026-10-29T23:30:00Z"))).toBe("Boa noite"); // 20h30
  });
});
