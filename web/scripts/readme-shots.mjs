// Imagens do README: só telas do /demo (dados fictícios), a partir dos screenshots dos testes
// de interface (`npx playwright test e2e/screenshots.spec.ts`), em WebP leve.
import { mkdirSync } from "node:fs";
import path from "node:path";

import sharp from "sharp";

const source = process.env.CAURI_SHOTS_DIR ?? path.resolve("..", "reference-private", "review");
const target = path.resolve("..", "docs", "screenshots");
mkdirSync(target, { recursive: true });

const shots = [
  ["demo-inicio-desktop-dobra.png", "inicio.webp", 1280],
  ["demo-carteira-desktop-dobra.png", "carteira.webp", 1280],
  ["demo-importar-desktop-dobra.png", "importar.webp", 1280],
  ["demo-assistente-desktop.png", "assistente.webp", 1280],
  ["demo-inicio-celular-dobra.png", "inicio-celular.webp", 390],
  ["demo-assistente-celular-dobra.png", "assistente-celular.webp", 390],
];
for (const [from, to, width] of shots) {
  const info = await sharp(path.join(source, from)).resize({ width }).webp({ quality: 78 }).toFile(path.join(target, to));
  console.log(`${to}: ${Math.round(info.size / 1024)} KB`);
}
