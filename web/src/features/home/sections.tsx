import { CalendarDays } from "lucide-react";
import { Bar, Cell, ComposedChart, Line, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { EvolutionPoint, Period } from "@/data/metrics";
import type { AgendaItem, Bucket, Goal, MovementRow } from "@/data/types";
import {
  formatBRL,
  formatBRLCompact,
  formatDate,
  formatDayMonth,
  formatMonthYear,
  formatPct,
} from "@/lib/format";
import { assetInitials, describe, originText } from "@/lib/movements";
import { tokens, type AssetClassKey } from "@/theme/tokens";
import { CardHeader, GlassCard } from "@/ui/GlassCard";
import { AssetAvatar, ProgressRing, Skeleton } from "@/ui/viz";

const classColor = (key: string) => tokens.assetClass[key as AssetClassKey]?.color ?? tokens.color.accent;
const classLabel = (key: string) => tokens.assetClass[key as AssetClassKey]?.label ?? key;

/* Evolução do patrimônio ------------------------------------------------------------ */

function EvolutionTooltip({ active, payload }: { active?: boolean; payload?: { payload: EvolutionPoint }[] }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="glass-card min-w-[190px] px-4 py-3 text-[13px]">
      <div className="mb-1.5 font-semibold">{formatDate(point.date)}</div>
      <div className="flex justify-between gap-4 text-muted">
        <span>Patrimônio</span>
        <span data-num className="text-ink">{formatBRL(point.marketValue)}</span>
      </div>
      {point.cdiEquivalent !== null ? (
        <div className="flex justify-between gap-4 text-muted">
          <span>No CDI</span>
          <span data-num style={{ color: tokens.color.chartLine }}>{formatBRL(point.cdiEquivalent)}</span>
        </div>
      ) : null}
    </div>
  );
}

export function EvolutionPanel({ points, period }: { points: EvolutionPoint[] | undefined; period: Period }) {
  const daily = period === "mes";
  return (
    <GlassCard className="flex min-h-[380px] flex-col" lift={false}>
      <CardHeader
        title="Evolução do patrimônio"
        subtitle={daily ? "Por pregão no mês" : "Fechamento de cada mês"}
        action={
          <div className="flex items-center gap-4 text-[12px] text-muted">
            <span className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-[3px]" style={{ background: tokens.color.chartBarActive }} /> Patrimônio
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-0.5 w-4 rounded" style={{ background: tokens.color.chartLine }} /> CDI, mesmos aportes
            </span>
          </div>
        }
      />
      {points ? (
        <div className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={points} margin={{ top: 8, right: 4, bottom: 0, left: 0 }} barCategoryGap="22%">
              <XAxis
                dataKey="date"
                tickFormatter={(d: string) => (daily ? formatDayMonth(d).day : formatMonthYear(d))}
                tick={{ fill: tokens.color.textSubtle, fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
                minTickGap={8}
              />
              <YAxis
                width={64}
                tickFormatter={(v: number) => formatBRLCompact(v).replace("R$ ", "")}
                tick={{ fill: tokens.color.textSubtle, fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                domain={[(min: number) => Math.floor((min * 0.85) / 10000) * 10000, "auto"]}
              />
              <Tooltip content={<EvolutionTooltip />} cursor={{ fill: "rgba(255,255,255,0.06)", radius: 10 }} />
              <Bar dataKey="marketValue" radius={[10, 10, 10, 10]} isAnimationActive={false}>
                {points.map((p) => (
                  <Cell
                    key={p.key}
                    fill={p.current ? tokens.color.chartBarActive : tokens.color.chartBar}
                    stroke={p.current ? "transparent" : "rgba(255,255,255,0.18)"}
                  />
                ))}
              </Bar>
              <Line
                dataKey="cdiEquivalent"
                type="monotone"
                stroke={tokens.color.chartLine}
                strokeWidth={2.2}
                dot={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <Skeleton className="h-[300px]" />
      )}
    </GlassCard>
  );
}

/* Agenda ---------------------------------------------------------------------------- */

export function AgendaPanel({ items }: { items: AgendaItem[] | undefined }) {
  return (
    <GlassCard className="flex flex-col" lift={false}>
      <CardHeader title="Agenda" subtitle="Proventos lançados e vencimentos" />
      {!items ? (
        <div className="space-y-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : items.length === 0 ? (
        <p className="text-[14px] text-muted">Nada agendado.</p>
      ) : (
        <ul className="space-y-3">
          {items.slice(0, 5).map((item) => {
            const { day, month } = formatDayMonth(item.event_date);
            const color = item.kind === "provento" ? tokens.color.gold : tokens.assetClass.renda_fixa.color;
            return (
              <li key={`${item.kind}-${item.label}-${item.event_date}`} className="glass-inset flex items-center gap-3 border-l-[3px] py-3 pr-3 pl-3.5" style={{ borderLeftColor: color }}>
                <div className="w-11 shrink-0 text-center leading-none">
                  <div data-num className="text-[18px] font-semibold">{day}</div>
                  <div className="mt-1 text-[11px] text-subtle uppercase">{month}</div>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[14px] font-medium">{item.label}</div>
                  <div className="text-[12px] text-muted">
                    {item.kind === "provento" ? `Provento (${item.detail ?? ""})` : `Vencimento ${item.detail ?? ""}, valor bruto`}
                  </div>
                </div>
                {item.amount !== null ? (
                  <div data-num className="shrink-0 text-[13px] font-semibold" style={{ color: item.kind === "provento" ? tokens.color.gold : undefined }}>
                    {formatBRL(item.amount)}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      <p className="mt-auto flex items-center gap-1.5 pt-4 text-[12px] text-subtle">
        <CalendarDays className="size-3.5" /> Proventos anunciados entram quando houver fonte.
      </p>
    </GlassCard>
  );
}

/* Últimas movimentações ------------------------------------------------------------- */

function OriginBadge({ m }: { m: MovementRow }) {
  return (
    <span className="shrink-0 rounded-full border border-white/15 bg-white/8 px-2 py-0.5 text-[11px] font-medium text-muted">
      {originText(m)}
    </span>
  );
}

export function RecentMovementsPanel({ items }: { items: MovementRow[] | undefined }) {
  return (
    <GlassCard className="flex flex-col">
      <CardHeader title="Últimas movimentações" />
      {!items ? (
        <div className="space-y-3">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-11" />
          ))}
        </div>
      ) : (
        <ul className="divide-y divide-white/8">
          {items.map((m) => {
            const color = classColor(m.asset_class);
            const short = assetInitials(m.asset_label);
            return (
              <li key={m.id} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
                <AssetAvatar initials={short} color={color} size={40} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[14px] font-medium">{m.asset_label}</div>
                  <div className="truncate text-[12px] text-muted">
                    {describe(m)} · {formatDate(m.trade_date)}
                  </div>
                </div>
                <OriginBadge m={m} />
              </li>
            );
          })}
        </ul>
      )}
    </GlassCard>
  );
}

/* Alocação por classe --------------------------------------------------------------- */

export function AllocationPanel({ buckets }: { buckets: Bucket[] | undefined }) {
  const total = buckets?.reduce((sum, b) => sum + b.market_value, 0) ?? 0;
  const data = (buckets ?? [])
    .map((b) => ({ key: b.bucket_key, value: b.market_value }))
    .filter((d) => d.value > 0)
    .sort((a, b) => b.value - a.value);
  return (
    <GlassCard className="flex flex-col">
      <CardHeader title="Alocação por classe" />
      {!buckets ? (
        <Skeleton className="h-48" />
      ) : (
        <div className="flex flex-1 flex-col items-center gap-5 sm:flex-row lg:flex-col xl:flex-row">
          <div className="relative size-[150px] shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data}
                  dataKey="value"
                  nameKey="key"
                  innerRadius="68%"
                  outerRadius="100%"
                  paddingAngle={2.5}
                  cornerRadius={6}
                  stroke="none"
                  isAnimationActive={false}
                >
                  {data.map((d) => (
                    <Cell key={d.key} fill={classColor(d.key)} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div className="absolute inset-0 grid place-items-center text-center">
              <div>
                <div className="text-[11px] text-subtle">Total</div>
                <div data-num className="text-[14px] font-semibold">{formatBRLCompact(total)}</div>
              </div>
            </div>
          </div>
          <ul className="w-full space-y-2">
            {data.map((d) => (
              <li key={d.key} className="flex items-center gap-2.5 text-[13px]">
                <span className="size-2.5 shrink-0 rounded-full" style={{ background: classColor(d.key) }} />
                <span className="flex-1 truncate text-muted">
                  {classLabel(d.key)}
                  {d.key === "renda_fixa" ? <span className="text-subtle"> (bruto)</span> : null}
                </span>
                <span data-num className="font-semibold">{formatPct(total ? d.value / total : 0)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </GlassCard>
  );
}

/* Meta -------------------------------------------------------------------------------- */

export function GoalPanel({ goal, current }: { goal: Goal | null | undefined; current: number | undefined }) {
  return (
    <GlassCard className="flex flex-col">
      <CardHeader title="Meta" subtitle={goal?.target_date ? `Até ${formatDate(goal.target_date)}` : undefined} />
      {goal === undefined || current === undefined ? (
        <Skeleton className="mx-auto size-[132px] rounded-full" />
      ) : goal === null ? (
        <p className="text-[14px] text-muted">Nenhuma meta definida.</p>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-4">
          <ProgressRing progress={current / goal.target_amount} color={tokens.color.gold}>
            <div>
              <div data-num className="text-[24px] font-semibold">{formatPct(current / goal.target_amount)}</div>
              <div className="text-[11px] text-subtle">da meta</div>
            </div>
          </ProgressRing>
          <div className="text-center text-[13px] text-muted">
            <span data-num className="font-semibold text-ink">{formatBRLCompact(current)}</span> de{" "}
            <span data-num>{formatBRLCompact(goal.target_amount)}</span>
          </div>
        </div>
      )}
    </GlassCard>
  );
}
