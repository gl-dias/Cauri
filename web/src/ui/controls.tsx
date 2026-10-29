import { motion, useReducedMotion } from "motion/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { tokens } from "@/theme/tokens";

/** Botão circular de vidro (barra superior). */
export function IconButton({
  label,
  children,
  badge,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode; badge?: number }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`glass-pill relative grid size-11 shrink-0 place-items-center text-ink transition-colors hover:bg-white/15 ${className}`}
      {...rest}
    >
      {children}
      {badge ? (
        <span className="absolute -top-0.5 -right-0.5 grid min-w-[18px] place-items-center rounded-full bg-primary px-1 text-[11px] leading-[18px] font-semibold text-white">
          {badge}
        </span>
      ) : null}
    </button>
  );
}

/** Botão de vidro com texto e ícone (ex.: Exportar). */
export function GlassButton({ children, className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`glass-pill inline-flex h-11 items-center gap-2 px-4 text-[14px] font-medium text-ink transition-colors hover:bg-white/15 ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/** Ação primária (azul). */
export function PrimaryButton({ children, className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`inline-flex h-11 items-center gap-2 rounded-full bg-primary px-5 text-[14px] font-semibold text-white shadow-card transition-colors hover:bg-primary-hover ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/** Controle segmentado: opção ativa numa pílula branca que desliza. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { key: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  const reduced = useReducedMotion();
  return (
    <div role="radiogroup" aria-label={label} className="glass-pill inline-flex h-11 items-center gap-0.5 p-1">
      {options.map((option) => {
        const active = option.key === value;
        return (
          <button
            key={option.key}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.key)}
            className={`relative h-9 rounded-full px-3.5 text-[13px] font-medium transition-colors sm:px-4 ${
              active ? "text-on-light" : "text-muted hover:text-ink"
            }`}
          >
            {active ? (
              <motion.span
                layoutId={`seg-${label}`}
                transition={reduced ? { duration: 0 } : tokens.motion.spring}
                className="absolute inset-0 rounded-full bg-white shadow-sm"
              />
            ) : null}
            <span className="relative">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Selo de variação: verde para ganho, vermelho para perda, neutro para o resto. */
export function DeltaBadge({ value, children, tone }: { value?: number; children: ReactNode; tone?: "gain" | "loss" | "neutral" }) {
  const resolved = tone ?? (value === undefined || Math.abs(value) < 1e-9 ? "neutral" : value > 0 ? "gain" : "loss");
  // Fundo escuro por baixo da tinta: o selo continua verde/vermelho e o texto passa no AA
  // mesmo quando o card está sobre a parte clara da foto.
  const styles = {
    gain: "text-gain [background:color-mix(in_srgb,var(--cauri-gain)_16%,rgba(0,0,0,0.45))]",
    loss: "text-loss [background:color-mix(in_srgb,var(--cauri-loss)_16%,rgba(0,0,0,0.45))]",
    neutral: "text-muted bg-black/30",
  }[resolved];
  return (
    <span data-num className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-semibold ${styles}`}>
      {children}
    </span>
  );
}
