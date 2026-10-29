// Referência visual: extrai frames do vídeo (ffmpeg via Docker, sem instalar nada) e monta
// comparações lado a lado com os screenshots do Cauri.
//
// Tudo fica em reference-private/ (ignorado pelo git): o vídeo e os prints são de
// terceiros e servem só de referência de estilo. Nada daqui vai para o repositório.
//
//   node scripts/compare-reference.mjs frames            # extrai frames de cada vídeo
//   node scripts/compare-reference.mjs pair <ref> <shot> <saida.png>

import { spawnSync } from "node:child_process";
import { mkdirSync, readdirSync } from "node:fs";
import path from "node:path";

import sharp from "sharp";

const REF_DIR = path.resolve("..", "reference-private");
const FRAMES_DIR = path.join(REF_DIR, "frames");
const FFMPEG_IMAGE = "jrottenberg/ffmpeg:7.1-alpine";

function extractFrames() {
  mkdirSync(FRAMES_DIR, { recursive: true });
  const videos = readdirSync(REF_DIR).filter((f) => /\.(mp4|mov|webm|mkv|m4v)$/i.test(f));
  if (videos.length === 0) {
    console.log(`nenhum vídeo em ${REF_DIR}`);
    return;
  }
  const mount = `${REF_DIR.replace(/\\/g, "/")}:/ref`;
  for (const video of videos) {
    const base = path.parse(video).name.replace(/[^\w-]+/g, "-");
    // Um frame por mudança de cena (telas diferentes), mais um a cada 4 s como rede.
    const args = [
      "run", "--rm", "-v", mount, FFMPEG_IMAGE, "-hide_banner", "-loglevel", "error",
      "-i", `/ref/${video}`,
      "-vf", "select='gt(scene,0.25)+not(mod(t\\,4))',scale=1440:-2",
      "-vsync", "vfr", "-frames:v", "60",
      `/ref/frames/${base}-%03d.png`,
    ];
    const result = spawnSync("docker", args, { stdio: "inherit" });
    if (result.status !== 0) throw new Error(`ffmpeg falhou em ${video}`);
  }
  const frames = readdirSync(FRAMES_DIR).filter((f) => f.endsWith(".png"));
  console.log(`${frames.length} frames em ${FRAMES_DIR}`);
}

async function label(text, width) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="44">
    <rect width="100%" height="100%" fill="#111"/>
    <text x="16" y="29" font-family="Segoe UI, Arial" font-size="20" fill="#fff">${text}</text></svg>`;
  return sharp(Buffer.from(svg)).png().toBuffer();
}

async function pair(refPath, shotPath, outPath) {
  const height = 900;
  const ref = await sharp(refPath).resize({ height }).toBuffer({ resolveWithObject: true });
  const shot = await sharp(shotPath).resize({ height }).toBuffer({ resolveWithObject: true });
  const gap = 24;
  const width = ref.info.width + gap + shot.info.width;
  await sharp({ create: { width, height: height + 44, channels: 3, background: "#111" } })
    .composite([
      { input: await label("Referência (só estilo)", ref.info.width), left: 0, top: 0 },
      { input: await label("Cauri /demo", shot.info.width), left: ref.info.width + gap, top: 0 },
      { input: ref.data, left: 0, top: 44 },
      { input: shot.data, left: ref.info.width + gap, top: 44 },
    ])
    .png()
    .toFile(outPath);
  console.log(`comparação: ${outPath}`);
}

const [command, ...rest] = process.argv.slice(2);
if (command === "frames") extractFrames();
else if (command === "pair" && rest.length === 3) await pair(rest[0], rest[1], rest[2]);
else console.log("uso: frames | pair <ref.png> <screenshot.png> <saida.png>");
