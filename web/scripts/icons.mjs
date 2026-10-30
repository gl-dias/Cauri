// Ícones PNG da tela de início (iPhone e Android), a partir do selo em docs/marca/09-selo.svg.
// O iPhone não usa o favicon SVG: sem apple-touch-icon ele monta uma letra sobre a cor do tema.
// Rodar de novo quando a marca mudar (`node scripts/icons.mjs`); os PNGs vão para public/.
//
// - apple-touch-icon.png (180) e icon-maskable-512.png: quadrado cheio, sem cantos
//   arredondados nem transparência (o sistema recorta o formato), selo dentro da área segura.
//   O do iPhone é escuro: atalho de site não acompanha o modo escuro do iOS (só app nativo
//   manda variações do ícone), e o PNG é guardado uma vez, ao adicionar; o grafite combina
//   com os ícones escuros do sistema. Para voltar ao creme, trocar IPHONE_BG por `paper`;
// - icon-192.png e icon-512.png: o ícone como no app, com os cantos arredondados.
import { readFileSync } from "node:fs";
import path from "node:path";

import sharp from "sharp";

const root = path.resolve(import.meta.dirname, "..");
const svg = readFileSync(path.resolve(root, "..", "docs", "marca", "09-selo.svg"), "utf8");
const match = svg.match(/^<svg[^>]*>(<rect[^>]*\/>)(.*)<\/svg>\s*$/s);
if (!match) throw new Error("09-selo.svg fora do formato esperado (rect do fundo e depois o selo)");
const [, tile, seal] = match;
const paper = tile.match(/fill="([^"]+)"/)[1];

const IPHONE_BG = "#1c1c1e";

const open = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">';
const rounded = `${open}${tile}${seal}</svg>`;
const fullBleed = (bg) =>
  `${open}<rect width="64" height="64" fill="${bg}"/><g transform="translate(32 32) scale(0.92) translate(-32 -32)">${seal}</g></svg>`;

const icons = [
  ["apple-touch-icon.png", fullBleed(IPHONE_BG), 180],
  ["icon-maskable-512.png", fullBleed(paper), 512],
  ["icon-192.png", rounded, 192],
  ["icon-512.png", rounded, 512],
];
for (const [file, source, size] of icons) {
  const info = await sharp(Buffer.from(source), { density: (72 * size) / 64 })
    .resize(size, size)
    .png({ compressionLevel: 9 })
    .toFile(path.join(root, "public", file));
  console.log(`${file}: ${size}px, ${Math.round(info.size / 1024)} KB`);
}
