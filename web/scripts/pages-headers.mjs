// Gera dist/_headers e dist/_redirects para o Cloudflare Pages, depois do build.
//
// A CSP libera conexão só para o Supabase e para a API configurados no build (as mesmas
// variáveis VITE_* que o app usa), mais o que a página precisa: fontes e imagens locais,
// áudio do microfone (blob) e estilos inline do Tailwind e do Motion.
//
// Sem as variáveis (CI, build local), cai nos endereços do ambiente local.
import { writeFileSync } from "node:fs";
import path from "node:path";

const dist = path.resolve(import.meta.dirname, "..", "dist");
const origin = (value, fallback) => new URL(value || fallback).origin;

const supabase = origin(process.env.VITE_SUPABASE_URL, "http://127.0.0.1:54321");
const api = origin(process.env.VITE_API_URL, "http://127.0.0.1:8000");
const supabaseWs = supabase.replace(/^http/, "ws");

const csp = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${supabase} ${supabaseWs} ${api}`,
  "media-src 'self' blob:",
  "worker-src 'self' blob:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

// Rotas que devolvem o HTML do app. O no-transform impede o Cloudflare de reescrever a
// página, o que inclui injetar o script do Web Analytics no domínio (bloqueado pela CSP de
// qualquer jeito, mas sujando o console). Fica só no HTML: em JS e imagens não há o que
// injetar, e o no-transform pode impedir a compressão na borda. Rota nova do app entra aqui.
// Cada rota casa com uma regra só, para não somar dois Cache-Control na mesma resposta.
const htmlRoutes = ["/", "/index.html", "/demo*", "/app*", "/login", "/entrar"];
const htmlRules = htmlRoutes
  .map((route) => `${route}\n  Cache-Control: public, max-age=0, must-revalidate, no-transform`)
  .join("\n\n");

const headers = `/*
  Content-Security-Policy: ${csp}
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: microphone=(self), camera=(), geolocation=(), payment=()
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  Cross-Origin-Opener-Policy: same-origin

${htmlRules}

/assets/*
  Cache-Control: public, max-age=31536000, immutable

/bg/*
  Cache-Control: public, max-age=2592000
`;

writeFileSync(path.join(dist, "_headers"), headers);
// SPA: qualquer rota que não seja arquivo cai no index.html (o React Router resolve).
writeFileSync(path.join(dist, "_redirects"), "/* /index.html 200\n");
console.log(`_headers: connect-src ${supabase} ${api}`);
