import { describe, expect, it } from "vitest";

import { countToImport, initialDecisions } from "../decisions";
import { SAMPLE_BATCH } from "../sample";

describe("decisões da importação", () => {
  it("duplicado começa mantendo o existente e não conta", () => {
    const decisions = initialDecisions(SAMPLE_BATCH);
    expect(Object.values(decisions)).toEqual(["keep_existing"]);
    expect(countToImport(SAMPLE_BATCH, decisions)).toBe(8);
  });

  it("substituir ou importar como nova passa a contar; erro e já importada nunca contam", () => {
    const [id] = Object.keys(initialDecisions(SAMPLE_BATCH));
    expect(countToImport(SAMPLE_BATCH, { [id!]: "replace" })).toBe(9);
    expect(countToImport(SAMPLE_BATCH, { [id!]: "import_new" })).toBe(9);
  });
});
