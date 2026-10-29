// Gera as versões otimizadas das fotos de fundo (AVIF e WebP em algumas larguras) e um
// placeholder borrado minúsculo, embutido em base64, para pintar a tela antes da foto chegar.
//
// Uso: node scripts/optimize-bg.mjs <pasta-com-os-originais>
// Os originais não vão para o repositório; ficam onde você baixou.

import { mkdir, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";

const OUT_DIR = path.resolve("public/bg");
const MANIFEST = path.resolve("src/theme/backgrounds.ts");
const WIDTHS = [1280, 1920, 2560];

// Créditos e licença da foto (a atribuição é opcional na licença do Pexels, mas fica
// registrada e aparece no rodapé). Escolhida entre três opções na Fase 3.
const PHOTOS = {
  "chale-entardecer": {
    title: "Chalé com janelas do chão ao teto ao entardecer",
    author: "Jonathan Borba",
    source: "https://www.pexels.com/photo/living-room-in-wooden-luxury-modern-hut-with-view-on-mountains-19737857/",
    license: "Pexels License",
    licenseUrl: "https://www.pexels.com/license/",
    position: "50% 40%",
    // céu claro no centro: véu mais forte (medido pelo e2e/contrast.spec.ts)
    overlay: ["rgba(0, 0, 0, 0.72)", "rgba(0, 0, 0, 0.62)"],
  },
};

const srcDir = process.argv[2];
if (!srcDir) {
  console.error("informe a pasta com os originais");
  process.exit(1);
}

await mkdir(OUT_DIR, { recursive: true });
const files = (await readdir(srcDir)).filter((f) => /\.(jpe?g|png)$/i.test(f));
const entries = [];

for (const file of files) {
  const slug = path.parse(file).name;
  const meta = PHOTOS[slug];
  if (!meta) continue;
  const input = path.join(srcDir, file);
  const { width: originalWidth } = await sharp(input).metadata();
  const widths = WIDTHS.filter((w) => w <= originalWidth);
  if (!widths.includes(Math.min(originalWidth, WIDTHS.at(-1)))) widths.push(originalWidth);

  const sizes = [];
  for (const width of widths) {
    const base = sharp(input).resize({ width, withoutEnlargement: true });
    const avif = path.join(OUT_DIR, `${slug}-${width}.avif`);
    const webp = path.join(OUT_DIR, `${slug}-${width}.webp`);
    const a = await base.clone().avif({ quality: 48, effort: 6 }).toFile(avif);
    const w = await base.clone().webp({ quality: 72, effort: 6 }).toFile(webp);
    sizes.push({ width, avifKb: Math.round(a.size / 1024), webpKb: Math.round(w.size / 1024) });
  }

  // Placeholder: 32 px de largura, borrado, ~0,5 KB em base64.
  const tiny = await sharp(input).resize({ width: 32 }).blur(1.2).webp({ quality: 45 }).toBuffer();
  const placeholder = `data:image/webp;base64,${tiny.toString("base64")}`;

  entries.push({ slug, ...meta, widths, placeholder, sizes });
  console.log(slug, sizes.map((s) => `${s.width}px: avif ${s.avifKb} KB, webp ${s.webpKb} KB`).join(" | "),
    `| placeholder ${tiny.length} B`);
}

const body = entries
  .map(
    (e) => `  "${e.slug}": {
    title: ${JSON.stringify(e.title)},
    author: ${JSON.stringify(e.author)},
    source: ${JSON.stringify(e.source)},
    license: ${JSON.stringify(e.license)},
    licenseUrl: ${JSON.stringify(e.licenseUrl)},
    position: ${JSON.stringify(e.position)},
    overlay: [${e.overlay.map((o) => JSON.stringify(o)).join(", ")}],
    widths: [${e.widths.join(", ")}],
    placeholder: ${JSON.stringify(e.placeholder)},
  },`,
  )
  .join("\n");

await writeFile(
  MANIFEST,
  `// Gerado por scripts/optimize-bg.mjs. Não editar à mão.
export type BackgroundPhoto = {
  title: string;
  author: string;
  source: string;
  license: string;
  licenseUrl: string;
  position: string;
  /** Véu escuro sobre a foto (topo, base), ajustado ao brilho de cada uma. */
  overlay: [string, string];
  widths: number[];
  placeholder: string;
};

export const BACKGROUNDS = {
${body}
} satisfies Record<string, BackgroundPhoto>;

export type BackgroundSlug = keyof typeof BACKGROUNDS;
`,
);
console.log(`manifesto: ${path.relative(process.cwd(), MANIFEST)}`);
