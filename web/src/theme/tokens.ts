/**
 * Tokens do tema: o único lugar onde ficam cores, blur, raios, sombras e movimento.
 * Trocar o visual é editar este arquivo; componentes só usam as variáveis CSS
 * (`--cauri-*`, aplicadas por `applyTheme`) e os nomes exportados aqui.
 */
import type { BackgroundSlug } from "./backgrounds";

export const tokens = {
  background: {
    photo: "chale-entardecer" satisfies BackgroundSlug as BackgroundSlug,
    // Véu escuro sobre a foto, para os números terem contraste (AA). Mais forte no topo,
    // onde as fotos têm o céu claro. Medido pelo e2e/contrast.spec.ts: se o contraste não
    // bater, aumenta-se aqui; nunca se diminui a fonte.
    overlayFrom: "rgba(0, 0, 0, 0.62)",
    overlayTo: "rgba(0, 0, 0, 0.56)",
  },
  color: {
    text: "#ffffff",
    textMuted: "rgba(255, 255, 255, 0.78)",
    textSubtle: "rgba(255, 255, 255, 0.70)",
    gain: "#34d399", // emerald-400
    loss: "#fb7185", // rose-400
    accent: "#60a5fa", // blue-400: destaque
    primary: "#3b82f6", // blue-500: ação primária
    primaryHover: "#2563eb",
    gold: "#f9d47e",
    avatarFrom: "#fdba74",
    avatarTo: "#f97316",
    onLight: "#111111",
    chartBar: "rgba(255, 255, 255, 0.22)",
    chartBarActive: "#60a5fa",
    chartLine: "#f9d47e",
    chartGrid: "rgba(255, 255, 255, 0.10)",
  },
  assetClass: {
    acao: { label: "Ações", color: "#60a5fa" },
    fii: { label: "FIIs", color: "#f9d47e" },
    renda_fixa: { label: "Renda fixa", color: "#34d399" },
    cripto: { label: "Cripto", color: "#a78bfa" },
    tesouro: { label: "Tesouro", color: "#f87171" },
  },
  glass: {
    fill: "rgba(255, 255, 255, 0.08)",
    fillStrong: "rgba(255, 255, 255, 0.16)",
    fillHover: "rgba(255, 255, 255, 0.14)",
    border: "rgba(255, 255, 255, 0.15)",
    highlight: "rgba(255, 255, 255, 0.34)",
    blur: "24px",
    blurMobile: "16px", // menos GPU na rolagem do celular
    saturate: "140%",
    tintOpacity: "0.16",
    // Navegadores sem backdrop-filter recebem vidro sólido.
    fallback: "rgba(30, 30, 35, 0.85)",
  },
  radius: {
    card: "22px",
    inner: "16px",
    pill: "999px",
  },
  shadow: {
    card: "0 8px 32px rgba(0, 0, 0, 0.25)",
    lifted: "0 14px 40px rgba(0, 0, 0, 0.32)",
  },
  font: {
    sans: "'Inter Variable', 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
  },
  motion: {
    stagger: 0.04,
    hoverLift: -5,
    spring: { type: "spring", stiffness: 320, damping: 26 } as const,
    pageFade: 0.28,
  },
} as const;

export type AssetClassKey = keyof typeof tokens.assetClass;

const cssVars: Record<string, string> = {
  "--cauri-text": tokens.color.text,
  "--cauri-text-muted": tokens.color.textMuted,
  "--cauri-text-subtle": tokens.color.textSubtle,
  "--cauri-gain": tokens.color.gain,
  "--cauri-loss": tokens.color.loss,
  "--cauri-accent": tokens.color.accent,
  "--cauri-primary": tokens.color.primary,
  "--cauri-primary-hover": tokens.color.primaryHover,
  "--cauri-gold": tokens.color.gold,
  "--cauri-avatar-from": tokens.color.avatarFrom,
  "--cauri-avatar-to": tokens.color.avatarTo,
  "--cauri-on-light": tokens.color.onLight,
  "--cauri-glass-fill": tokens.glass.fill,
  "--cauri-glass-fill-strong": tokens.glass.fillStrong,
  "--cauri-glass-fill-hover": tokens.glass.fillHover,
  "--cauri-glass-border": tokens.glass.border,
  "--cauri-glass-highlight": tokens.glass.highlight,
  "--cauri-glass-blur": tokens.glass.blur,
  "--cauri-glass-blur-mobile": tokens.glass.blurMobile,
  "--cauri-glass-saturate": tokens.glass.saturate,
  "--cauri-glass-tint-opacity": tokens.glass.tintOpacity,
  "--cauri-glass-fallback": tokens.glass.fallback,
  "--cauri-radius-card": tokens.radius.card,
  "--cauri-radius-inner": tokens.radius.inner,
  "--cauri-radius-pill": tokens.radius.pill,
  "--cauri-shadow-card": tokens.shadow.card,
  "--cauri-shadow-lifted": tokens.shadow.lifted,
  "--cauri-font-sans": tokens.font.sans,
  "--cauri-overlay-from": tokens.background.overlayFrom,
  "--cauri-overlay-to": tokens.background.overlayTo,
  ...Object.fromEntries(
    Object.entries(tokens.assetClass).map(([key, value]) => [`--cauri-class-${key}`, value.color]),
  ),
};

/** Escreve os tokens como variáveis CSS no :root. Chamado uma vez, antes do render. */
export function applyTheme(root: HTMLElement = document.documentElement): void {
  for (const [name, value] of Object.entries(cssVars)) root.style.setProperty(name, value);
}
