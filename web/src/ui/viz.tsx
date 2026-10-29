import { animate, useReducedMotion } from "motion/react";
import { useEffect, useId, useRef, useState } from "react";

/** Linha fina sem eixos, com um degradê embaixo, na cor do card. */
export function Sparkline({ values, color, height = 36 }: { values: number[]; color: string; height?: number }) {
  const id = useId();
  if (values.length < 2) return <div style={{ height }} />;
  const width = 120;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width;
    const y = height - 3 - ((v - min) / span) * (height - 6);
    return [x, y] as const;
  });
  const line = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="block w-full" style={{ height }} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.35" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Número que conta até o valor ao carregar (sem animação com prefers-reduced-motion). */
export function AnimatedNumber({ value, format, duration = 0.9 }: { value: number; format: (v: number) => string; duration?: number }) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(reduced ? value : 0);
  const from = useRef(0);
  useEffect(() => {
    if (reduced) {
      setShown(value);
      return;
    }
    const controls = animate(from.current, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setShown(v),
    });
    from.current = value;
    return () => controls.stop();
  }, [value, reduced, duration]);
  return (
    <span data-num aria-label={format(value)}>
      <span aria-hidden>{format(shown)}</span>
    </span>
  );
}

/** Anel de progresso (Meta). */
export function ProgressRing({ progress, color, size = 132, stroke = 12, children }: {
  progress: number;
  color: string;
  size?: number;
  stroke?: number;
  children?: React.ReactNode;
}) {
  const reduced = useReducedMotion();
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(1, progress));
  const [drawn, setDrawn] = useState(reduced ? clamped : 0);
  useEffect(() => {
    if (reduced) {
      setDrawn(clamped);
      return;
    }
    const controls = animate(0, clamped, { duration: 1.1, ease: [0.22, 1, 0.36, 1], onUpdate: setDrawn });
    return () => controls.stop();
  }, [clamped, reduced]);
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - drawn)}
          style={{ filter: `drop-shadow(0 0 8px ${color}66)` }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">{children}</div>
    </div>
  );
}

/** Avatar redondo com iniciais escuras sobre degradê laranja (branco no laranja não passa no AA). */
export function Avatar({ name, size = 44 }: { name: string; size?: number }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
  return (
    <span
      aria-label={name}
      data-contrast="fundo-proprio"
      className="grid shrink-0 place-items-center rounded-full font-semibold text-on-light shadow-card ring-2 ring-white/25"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.36,
        background: "linear-gradient(135deg, var(--cauri-avatar-from), var(--cauri-avatar-to))",
      }}
    >
      {initials || "?"}
    </span>
  );
}

/** Bloco de carregamento no formato do conteúdo. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-white/10 ${className}`} />;
}

/** Sigla do ativo num círculo na cor da classe (cor clareada sobre fundo escuro: passa no AA). */
export function AssetAvatar({ initials, color, size = 36 }: { initials: string; color: string; size?: number }) {
  return (
    <span
      aria-hidden
      className="grid shrink-0 place-items-center rounded-full font-bold tracking-tight"
      style={{
        width: size,
        height: size,
        fontSize: initials.length > 3 ? 10.5 : 11.5,
        background: `color-mix(in srgb, ${color} 28%, rgba(0, 0, 0, 0.55))`,
        color: `color-mix(in srgb, ${color} 55%, white)`,
      }}
    >
      {initials}
    </span>
  );
}
