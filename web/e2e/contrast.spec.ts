import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";
import sharp from "sharp";

import { openScreen, SCREENS } from "./screens";

/**
 * Contraste AA dos textos sobre o vidro. O fundo real atrás de cada texto (foto + véu +
 * vidro) é estimado pela mediana de uma moldura de pixels em volta do texto; a cor do
 * texto (branco com opacidade) é composta sobre esse fundo. AA: 4,5:1 para texto
 * normal e 3:1 para texto grande (>= 24 px, ou >= 18,66 px em negrito).
 */
const OUT = process.env.CAURI_SHOTS_DIR ?? path.resolve("..", "reference-private", "review");
mkdirSync(OUT, { recursive: true });

type Box = { x: number; y: number; w: number; h: number };
type Sample = Box & { text: string; color: string; size: number; weight: number; clip: Box | null };

function parseColor(css: string): [number, number, number, number] {
  const m = css.match(/rgba?\(([^)]+)\)/);
  if (!m?.[1]) return [255, 255, 255, 1];
  const parts = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
  return [parts[0] ?? 255, parts[1] ?? 255, parts[2] ?? 255, parts[3] ?? 1];
}

function luminance([r, g, b]: number[]): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r ?? 0) + 0.7152 * lin(g ?? 0) + 0.0722 * lin(b ?? 0);
}

const median = (values: number[]) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] ?? 0;
};

for (const screen of SCREENS) {
  test(`contraste AA: ${screen.name}`, async ({ page }, info) => {
    await openScreen(page, screen);
    const shot = await page.screenshot();
    const { data, info: img } = await sharp(shot).raw().toBuffer({ resolveWithObject: true });
    const scale = img.width / page.viewportSize()!.width;

    const samples: Sample[] = await page.evaluate(() => {
      const out: Sample[] = [];
      // Com um diálogo aberto, o resto da página fica inerte atrás do véu: mede só o diálogo.
      const root = document.querySelector("[role='dialog']") ?? document.querySelector("#root")!;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode as Text;
        const text = node.textContent?.trim();
        const el = node.parentElement;
        // Texto sobre fundo opaco próprio (avatar): a moldura em volta não representa o fundo.
        if (!text || !el || el.closest("svg") || el.closest("[data-contrast='fundo-proprio']")) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        const r = range.getBoundingClientRect();
        if (r.width < 4 || r.height < 6 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
        const style = getComputedStyle(el);
        if (style.visibility === "hidden" || Number(style.opacity) === 0) continue;
        // ÚNICA exceção de visibilidade: texto escondido atrás de uma barra fixa (barra de ação
        // da importação, dock do celular ou barra do topo: position fixed ou sticky). Ali o que
        // aparece é a barra, e o texto dela é medido por conta própria. Qualquer outra
        // sobreposição continua medida normalmente.
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        if (hit && !el.contains(hit) && !hit.contains(el)) {
          let bar: Element | null = hit;
          while (bar && !["fixed", "sticky"].includes(getComputedStyle(bar).position)) bar = bar.parentElement;
          if (bar && !bar.contains(el)) continue;
        }
        // Se o texto está dentro de um elemento com fundo próprio pequeno (selo, pílula
        // ativa), a amostra fica dentro dele: é esse fundo que está atrás das letras.
        let clip: { x: number; y: number; w: number; h: number } | null = null;
        let cur: HTMLElement | null = el;
        for (let depth = 0; cur && depth < 3; depth++, cur = cur.parentElement) {
          const cs = getComputedStyle(cur);
          const opaqueBg = cs.backgroundImage !== "none" || !/rgba\(.*,\s*0\)|transparent/.test(cs.backgroundColor);
          const b = cur.getBoundingClientRect();
          if (opaqueBg && b.height < 48) {
            clip = { x: b.left, y: b.top, w: b.width, h: b.height };
            break;
          }
        }
        out.push({
          text: text.slice(0, 40),
          x: r.left, y: r.top, w: r.width, h: r.height,
          color: style.color,
          size: parseFloat(style.fontSize),
          weight: Number(style.fontWeight),
          clip,
        });
      }
      return out;
    });

    const results = samples.map((s) => {
      // Moldura de 2 a 6 px em volta da caixa do texto: só pixels de fundo, sem as letras.
      const inner = { x0: (s.x - 2) * scale, y0: (s.y - 2) * scale, x1: (s.x + s.w + 2) * scale, y1: (s.y + s.h + 2) * scale };
      const lim = s.clip ?? { x: -1e9, y: -1e9, w: 2e9, h: 2e9 };
      const x0 = Math.max(0, Math.round(Math.max(s.x - 6, lim.x) * scale));
      const y0 = Math.max(0, Math.round(Math.max(s.y - 6, lim.y) * scale));
      const x1 = Math.min(img.width, Math.round(Math.min(s.x + s.w + 6, lim.x + lim.w) * scale));
      const y1 = Math.min(img.height, Math.round(Math.min(s.y + s.h + 6, lim.y + lim.h) * scale));
      const rs: number[] = [], gs: number[] = [], bs: number[] = [];
      // Em selos e pílulas, os cantos arredondados mostram o fundo de fora: amostra só as
      // faixas laterais, na altura do miolo do texto, que ficam dentro da pílula.
      const band = s.clip
        ? { y0: (s.y + s.h * 0.25) * scale, y1: (s.y + s.h * 0.75) * scale }
        : { y0: -1e9, y1: 1e9 };
      for (let y = y0; y < y1; y++) {
        if (y < band.y0 || y > band.y1) continue;
        for (let x = x0; x < x1; x++) {
          if (x >= inner.x0 && x <= inner.x1 && y >= inner.y0 && y <= inner.y1) continue;
          const i = (y * img.width + x) * img.channels;
          rs.push(data[i]!); gs.push(data[i + 1]!); bs.push(data[i + 2]!);
        }
      }
      const bgColor = [median(rs), median(gs), median(bs)];
      const [tr, tg, tb, ta] = parseColor(s.color);
      const fg = [tr * ta + bgColor[0]! * (1 - ta), tg * ta + bgColor[1]! * (1 - ta), tb * ta + bgColor[2]! * (1 - ta)];
      const l1 = luminance(fg), l2 = luminance(bgColor);
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      const large = s.size >= 24 || (s.size >= 18.66 && s.weight >= 700);
      return { ...s, ratio: Math.round(ratio * 100) / 100, needed: large ? 3 : 4.5 };
    });

    const failures = results.filter((r) => r.ratio < r.needed).sort((a, b) => a.ratio - b.ratio);
    writeFileSync(
      path.join(OUT, `contraste-${screen.name}-${info.project.name}.json`),
      JSON.stringify({ min: Math.min(...results.map((r) => r.ratio)), failures, total: results.length }, null, 2),
    );
    expect(failures.map((f) => `${f.text} (${f.ratio}:1, precisa ${f.needed}:1)`)).toEqual([]);
  });
}
