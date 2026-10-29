import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { GlassCard } from "./GlassCard";
import { Sparkline } from "./viz";

export function KpiCard({
  icon: Icon,
  color,
  label,
  value,
  badge,
  footnote,
  spark,
}: {
  icon: LucideIcon;
  color: string;
  label: string;
  value: ReactNode;
  badge?: ReactNode;
  footnote?: ReactNode;
  spark: number[];
}) {
  return (
    <GlassCard className="flex min-w-[260px] snap-start flex-col gap-4 md:min-w-0">
      <div className="flex items-center gap-3">
        <span
          className="grid size-10 shrink-0 place-items-center rounded-[13px]"
          style={{ background: `color-mix(in srgb, ${color} 22%, transparent)`, color }}
          aria-hidden
        >
          <Icon className="size-5" strokeWidth={2} />
        </span>
        <span className="text-[14px] font-medium text-muted">{label}</span>
      </div>
      <div>
        <div className="text-[26px] leading-tight font-semibold tracking-tight sm:text-[28px]">{value}</div>
        <div className="mt-2 flex min-h-6 flex-wrap items-center gap-2 text-[12px] text-subtle">
          {badge}
          {footnote ? <span>{footnote}</span> : null}
        </div>
      </div>
      <Sparkline values={spark} color={color} />
    </GlassCard>
  );
}
