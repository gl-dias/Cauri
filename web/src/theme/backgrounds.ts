// Gerado por scripts/optimize-bg.mjs. Não editar à mão.
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
  "chale-entardecer": {
    title: "Chalé com janelas do chão ao teto ao entardecer",
    author: "Jonathan Borba",
    source: "https://www.pexels.com/photo/living-room-in-wooden-luxury-modern-hut-with-view-on-mountains-19737857/",
    license: "Pexels License",
    licenseUrl: "https://www.pexels.com/license/",
    position: "50% 40%",
    overlay: ["rgba(0, 0, 0, 0.72)", "rgba(0, 0, 0, 0.62)"],
    widths: [1280, 1920, 2560],
    placeholder: "data:image/webp;base64,UklGRqwAAABXRUJQVlA4IKAAAACQBQCdASogABUAPtlcokyoJSMiMAwBABsJagCdMoPNJC08I3oRIPZ4kSAMhRbLb05xzvW+AAD+48cvUXuoSlSFl/H1whBwGxBCM4NgdDLPS2kT4g7o9k3MgScXREl83+C7pavTlOrSS0x5hQdskvWh+11lFqejgFrHzMk9MRlqH07FSznwHt8BqSk3Q7DMGtMHiLGIQ+jLklWudpkrRAAA",
  },
} satisfies Record<string, BackgroundPhoto>;

export type BackgroundSlug = keyof typeof BACKGROUNDS;
