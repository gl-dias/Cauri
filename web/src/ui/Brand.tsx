/**
 * Marca do Cauri: o selo de cera com o búzio em relevo (cauri é o búzio, uma das moedas mais
 * antigas do mundo) e o nome em Instrument Serif. O favicon (public/favicon.svg) é o mesmo
 * selo. As outras propostas de logo ficam guardadas em docs/marca/.
 */

const SEAL = "#8f2d33";
const SCALLOPS = Array.from({ length: 16 }, (_, i) => {
  const angle = (i * Math.PI) / 8;
  return [32 + 21 * Math.cos(angle), 32 + 21 * Math.sin(angle)].map((v) => Math.round(v * 100) / 100);
});

export function BrandMark({ className = "size-10" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={`shrink-0 ${className}`} aria-hidden>
      <rect width="64" height="64" rx="15" fill="#efe6d6" />
      <g fill={SEAL}>
        <circle cx="32" cy="32" r="21" />
        {SCALLOPS.map(([x, y]) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r="4.2" />
        ))}
      </g>
      <ellipse cx="32.8" cy="32.8" rx="8" ry="11.5" fill="#6e1f25" />
      <ellipse cx="32" cy="32" rx="8" ry="11.5" fill="#b4444a" />
      <path d="M32 21.5V42.5" stroke="#5f1a20" strokeWidth="2.6" strokeLinecap="round" />
    </svg>
  );
}

/** Selo + nome, como aparece na barra do app e nas telas de acesso. */
export function Brand() {
  return (
    <span className="flex items-center gap-2.5">
      <BrandMark className="size-10 drop-shadow-[0_6px_18px_rgba(0,0,0,0.3)]" />
      <span className="font-brand text-[27px] leading-none">Cauri</span>
    </span>
  );
}
