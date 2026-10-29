import { describe, expect, it } from "vitest";

import { guessMapping, missingForProfile } from "../mapping";

describe("mapeamento de colunas", () => {
  it("sugere pelos nomes, sem acento e sem repetir coluna", () => {
    const columns = ["Data Operação", "Operação", "Papel", "Qtde", "Preço", "Valor Total", "Corretagem"];
    expect(guessMapping(columns)).toEqual({
      data: "Data Operação",
      tipo: "Operação",
      ativo: "Papel",
      quantidade: "Qtde",
      preco: "Preço",
      valor: "Valor Total",
      taxa: "Corretagem",
    });
  });

  it("entende cabeçalhos em inglês de exchange", () => {
    expect(guessMapping(["Date", "Side", "Coin", "Amount", "Price", "Fee", "Fee Coin"])).toMatchObject({
      data: "Date",
      tipo: "Side",
      ativo: "Coin",
      quantidade: "Amount",
      ativo_taxa: "Fee Coin",
    });
  });

  it("lista o que falta para salvar", () => {
    expect(missingForProfile({ data: "Data" }, "", "")).toEqual([
      "Tipo de operação",
      "Ativo",
      "Quantidade ou Valor total",
      "Corretora (coluna ou fixa)",
      "Nome do perfil",
    ]);
    expect(missingForProfile({ data: "D", tipo: "T", ativo: "A", quantidade: "Q" }, "xp", "Minha corretora")).toEqual([]);
  });
});
