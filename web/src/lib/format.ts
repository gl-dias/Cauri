/** Formatação pt-BR. Datas chegam como "AAAA-MM-DD" e nunca passam por fuso horário. */

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const brlCompact = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  notation: "compact",
  maximumFractionDigits: 1,
});
const pct = new Intl.NumberFormat("pt-BR", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const pctSigned = new Intl.NumberFormat("pt-BR", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: "exceptZero",
});
const decimal = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 8 });

// Sinal de menos tipográfico (U+2212): com algarismos tabulares, o hífen fica largo e
// parece separado do número.
const MINUS = "−";
const typographicMinus = (text: string) => text.replace(/^-/, MINUS);

const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

/** R$ 1.234,56 (espaço normal entre R$ e o número, como no resto do texto). */
export function formatBRL(value: number): string {
  return typographicMinus(brl.format(value).replace(/ /g, " "));
}

export function formatBRLSigned(value: number): string {
  const text = formatBRL(Math.abs(value));
  if (Math.abs(value) < 0.005) return text;
  return `${value > 0 ? "+" : MINUS}${text}`;
}

/** R$ 140,7 mil */
export function formatBRLCompact(value: number): string {
  return brlCompact.format(value).replace(/ /g, " ");
}

export function formatPct(value: number): string {
  return typographicMinus(pct.format(value).replace(/ /g, ""));
}

export function formatPctSigned(value: number): string {
  return typographicMinus(pctSigned.format(value).replace(/ /g, ""));
}

/** Diferença em pontos percentuais: -2,6 p.p. */
export function formatPP(value: number): string {
  const points = value * 100;
  const text = Math.abs(points).toFixed(1).replace(".", ",");
  if (Math.abs(points) < 0.05) return "0,0 p.p.";
  return `${points > 0 ? "+" : MINUS}${text} p.p.`;
}

export function formatQuantity(value: number): string {
  return decimal.format(value);
}

function parts(iso: string): [number, number, number] {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return [y ?? 0, m ?? 1, d ?? 1];
}

/** 28/10/2026 */
export function formatDate(iso: string): string {
  const [y, m, d] = parts(iso);
  return `${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}/${y}`;
}

/** 05 nov */
export function formatDayMonth(iso: string): { day: string; month: string } {
  const [, m, d] = parts(iso);
  return { day: String(d).padStart(2, "0"), month: MONTHS[m - 1] ?? "" };
}

/** out/26 */
export function formatMonthYear(iso: string): string {
  const [y, m] = parts(iso);
  return `${MONTHS[m - 1] ?? ""}/${String(y).slice(2)}`;
}

/** Saudação pelo horário de Brasília. */
export function greeting(now: Date = new Date()): string {
  const hour = Number(
    new Intl.DateTimeFormat("pt-BR", { hour: "numeric", hour12: false, timeZone: "America/Sao_Paulo" }).format(now),
  );
  if (hour >= 5 && hour < 12) return "Bom dia";
  if (hour >= 12 && hour < 18) return "Boa tarde";
  return "Boa noite";
}
