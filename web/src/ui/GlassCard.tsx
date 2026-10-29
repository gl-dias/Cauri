import { motion, useReducedMotion, type HTMLMotionProps } from "motion/react";
import type { CSSProperties, ReactNode } from "react";

import { hoverLift, itemVariants, staticVariants } from "./motion";

type GlassCardProps = Omit<HTMLMotionProps<"section">, "children"> & {
  children: ReactNode;
  /** Cor da classe de ativo: vira vidro tingido. */
  tint?: string;
  /** Sobe 5 px no hover (desligado com prefers-reduced-motion). */
  lift?: boolean;
  padded?: boolean;
};

export function GlassCard({ children, tint, lift = true, padded = true, className = "", style, ...rest }: GlassCardProps) {
  const reduced = useReducedMotion();
  const tintStyle = tint ? ({ "--tint": tint } as CSSProperties) : undefined;
  return (
    <motion.section
      variants={reduced ? staticVariants : itemVariants}
      whileHover={lift && !reduced ? hoverLift : undefined}
      className={`glass-card ${tint ? "glass-tinted" : ""} ${padded ? "p-5 sm:p-6" : ""} ${className}`}
      style={{ ...tintStyle, ...style }}
      {...rest}
    >
      {children}
    </motion.section>
  );
}

export function CardHeader({ title, action, subtitle }: { title: string; action?: ReactNode; subtitle?: ReactNode }) {
  return (
    <header className="mb-4 flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p> : null}
      </div>
      {action}
    </header>
  );
}
