import { useState } from "react";

import { BACKGROUNDS, type BackgroundSlug } from "@/theme/backgrounds";
import { tokens } from "@/theme/tokens";

// O véu de cada foto fica no manifesto (backgrounds.ts), ajustado ao brilho dela.

/**
 * Foto de fundo em tela cheia, fixa. Enquanto a foto carrega, aparece o placeholder
 * borrado (embutido, ~150 bytes). Por cima, o véu escuro em degradê que garante o
 * contraste dos números.
 */
export function Background({ slug = tokens.background.photo }: { slug?: BackgroundSlug }) {
  const photo = BACKGROUNDS[slug];
  const [loaded, setLoaded] = useState(false);
  const srcset = (ext: "avif" | "webp") => photo.widths.map((w) => `/bg/${slug}-${w}.${ext} ${w}w`).join(", ");
  const fallbackWidth = photo.widths.at(-1);
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div
        className="absolute inset-0 scale-110 bg-cover blur-2xl"
        style={{ backgroundImage: `url("${photo.placeholder}")`, backgroundPosition: photo.position }}
      />
      <picture>
        <source type="image/avif" srcSet={srcset("avif")} sizes="100vw" />
        <source type="image/webp" srcSet={srcset("webp")} sizes="100vw" />
        <img
          src={`/bg/${slug}-${fallbackWidth}.webp`}
          alt=""
          decoding="async"
          fetchPriority="high"
          onLoad={() => setLoaded(true)}
          className={`absolute inset-0 size-full object-cover transition-opacity duration-700 ${loaded ? "opacity-100" : "opacity-0"}`}
          style={{ objectPosition: photo.position }}
        />
      </picture>
      <div
        className="absolute inset-0"
        style={{ background: `linear-gradient(180deg, ${photo.overlay[0]}, ${photo.overlay[1]})` }}
      />
    </div>
  );
}
