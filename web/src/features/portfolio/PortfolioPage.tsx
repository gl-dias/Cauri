import { Plus } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useMemo, useState } from "react";

import { useAppSource, useBuckets, usePositions } from "@/data/context";
import type { Position } from "@/data/types";
import { formatBRL, formatDate, formatPct, formatPctSigned, formatQuantity } from "@/lib/format";
import { assetInitials } from "@/lib/movements";
import { tokens, type AssetClassKey } from "@/theme/tokens";
import { DeltaBadge, PrimaryButton } from "@/ui/controls";
import { FilterPills } from "@/ui/forms";
import { CardHeader, GlassCard } from "@/ui/GlassCard";
import { pageVariants, staticVariants } from "@/ui/motion";
import { AssetAvatar, Skeleton } from "@/ui/viz";

import { ManualEntryDialog } from "../ledger/dialogs";

const CLASSES = Object.keys(tokens.assetClass) as AssetClassKey[];

type ClassSummary = { key: AssetClassKey; value: number; cost: number; count: number };

function summarize(positions: Position[]): ClassSummary[] {
  return CLASSES.map((key) => {
    const rows = positions.filter((p) => p.asset_class === key);
    return {
      key,
      value: rows.reduce((s, p) => s + p.market_value, 0),
      cost: rows.reduce((s, p) => s + p.cost_basis, 0),
      count: new Set(rows.map((p) => p.asset_id ?? p.instrument_id)).size,
    };
  }).filter((c) => c.count > 0);
}

function Rentab({ value, cost }: { value: number; cost: number }) {
  if (cost <= 0) return null;
  const r = value / cost - 1;
  return <span data-num className={r >= 0 ? "text-gain" : "text-loss"}>{formatPctSigned(r)}</span>;
}

function PriceCell({ p }: { p: Position }) {
  if (p.price === null) return <span className="text-subtle">sem cotação</span>;
  return (
    <span className="inline-flex flex-col items-end">
      <span data-num>{formatBRL(p.price)}</span>
      {p.price_status !== "ok" && p.price_date ? (
        <span className="text-[11px] text-gold">desde {formatDate(p.price_date)}</span>
      ) : null}
    </span>
  );
}

function AssetLabel({ p }: { p: Position }) {
  const color = tokens.assetClass[p.asset_class].color;
  return (
    <div className="flex min-w-0 items-center gap-3">
      <AssetAvatar initials={assetInitials(p.label)} color={color} />
      <div className="min-w-0">
        <div className="truncate font-medium">{p.label}</div>
        {p.name && p.name !== p.label ? <div className="truncate text-[12px] text-subtle">{p.name}</div> : null}
      </div>
    </div>
  );
}

function TradedTable({ rows }: { rows: Position[] }) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[760px] text-left text-[13px]">
          <thead>
            <tr className="border-b border-white/10 text-[12px] text-subtle">
              <th className="py-2.5 pr-3 font-medium">Ativo</th>
              <th className="py-2.5 pr-3 font-medium">Corretora</th>
              <th className="py-2.5 pr-3 text-right font-medium">Quantidade</th>
              <th className="py-2.5 pr-3 text-right font-medium">Preço médio</th>
              <th className="py-2.5 pr-3 text-right font-medium">Preço atual</th>
              <th className="py-2.5 pr-3 text-right font-medium">Valor</th>
              <th className="py-2.5 text-right font-medium">Rentabilidade</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.06]">
            {rows.map((p) => (
              <tr key={`${p.asset_id}-${p.broker_id}`}>
                <td className="max-w-[260px] py-2.5 pr-3"><AssetLabel p={p} /></td>
                <td className="py-2.5 pr-3 text-muted">{p.broker_name}</td>
                <td data-num className="py-2.5 pr-3 text-right">{p.quantity !== null ? formatQuantity(p.quantity) : ""}</td>
                <td data-num className="py-2.5 pr-3 text-right">{p.avg_cost !== null ? formatBRL(p.avg_cost) : ""}</td>
                <td className="py-2.5 pr-3 text-right"><PriceCell p={p} /></td>
                <td data-num className="py-2.5 pr-3 text-right font-medium">{formatBRL(p.market_value)}</td>
                <td className="py-2.5 text-right"><Rentab value={p.market_value} cost={p.cost_basis} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="space-y-2.5 md:hidden">
        {rows.map((p) => (
          <li key={`${p.asset_id}-${p.broker_id}`} className="glass-inset space-y-2 p-3.5 text-[13px]">
            <div className="flex items-start justify-between gap-3">
              <AssetLabel p={p} />
              <div className="text-right">
                <div data-num className="font-semibold">{formatBRL(p.market_value)}</div>
                <Rentab value={p.market_value} cost={p.cost_basis} />
              </div>
            </div>
            <div className="flex justify-between text-muted">
              <span>
                <span data-num>{p.quantity !== null ? formatQuantity(p.quantity) : ""}</span> · PM{" "}
                <span data-num>{p.avg_cost !== null ? formatBRL(p.avg_cost) : ""}</span>
              </span>
              <PriceCell p={p} />
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

function FixedIncomeTable({ rows }: { rows: Position[] }) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[720px] text-left text-[13px]">
          <thead>
            <tr className="border-b border-white/10 text-[12px] text-subtle">
              <th className="py-2.5 pr-3 font-medium">Título</th>
              <th className="py-2.5 pr-3 font-medium">Corretora</th>
              <th className="py-2.5 pr-3 font-medium">Vencimento</th>
              <th className="py-2.5 pr-3 text-right font-medium">Aplicado</th>
              <th className="py-2.5 pr-3 text-right font-medium">Valor bruto</th>
              <th className="py-2.5 text-right font-medium">Rendimento bruto</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.06]">
            {rows.map((p) => (
              <tr key={`${p.instrument_id}-${p.broker_id}`}>
                <td className="max-w-[300px] py-2.5 pr-3"><AssetLabel p={p} /></td>
                <td className="py-2.5 pr-3 text-muted">{p.broker_name}</td>
                <td data-num className="py-2.5 pr-3 text-muted">{p.fi_maturity_date ? formatDate(p.fi_maturity_date) : ""}</td>
                <td data-num className="py-2.5 pr-3 text-right">{formatBRL(p.cost_basis)}</td>
                <td data-num className="py-2.5 pr-3 text-right font-medium">{formatBRL(p.market_value)}</td>
                <td className="py-2.5 text-right"><Rentab value={p.market_value} cost={p.cost_basis} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="space-y-2.5 md:hidden">
        {rows.map((p) => (
          <li key={`${p.instrument_id}-${p.broker_id}`} className="glass-inset flex items-start justify-between gap-3 p-3.5 text-[13px]">
            <AssetLabel p={p} />
            <div className="text-right">
              <div data-num className="font-semibold">{formatBRL(p.market_value)}</div>
              <Rentab value={p.market_value} cost={p.cost_basis} />
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

export function PortfolioPage() {
  const reduced = useReducedMotion();
  const app = useAppSource();
  const positions = usePositions();
  const lastDay = positions.data?.[0]?.snap_date;
  const classBuckets = useBuckets(lastDay, "class");
  const [assetClass, setAssetClass] = useState<"todas" | AssetClassKey>("todas");
  const [broker, setBroker] = useState<string>("todas");
  const [creating, setCreating] = useState(false);

  const brokers = useMemo(() => {
    const seen = new Map<string, string>();
    for (const p of positions.data ?? []) seen.set(p.broker_id, p.broker_name ?? p.broker_id);
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [positions.data]);

  const byBroker = useMemo(
    () => (positions.data ?? []).filter((p) => broker === "todas" || p.broker_id === broker),
    [positions.data, broker],
  );
  const summaries = useMemo(() => summarize(byBroker), [byBroker]);
  const total = summaries.reduce((s, c) => s + c.value, 0);
  const visible = byBroker.filter((p) => assetClass === "todas" || p.asset_class === assetClass);
  const traded = visible.filter((p) => p.asset_class !== "renda_fixa");
  const fixed = visible.filter((p) => p.asset_class === "renda_fixa");
  const twr = (key: AssetClassKey) => classBuckets.data?.find((b) => b.bucket_key === key)?.quota_value;

  return (
    <motion.div variants={reduced ? staticVariants : pageVariants} initial="hidden" animate="show" className="space-y-5 sm:space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight sm:text-[34px]">Carteira</h1>
          <p className="mt-1 text-[14px] text-muted">
            {lastDay ? `Posição no fechamento de ${formatDate(lastDay)}` : "Carregando..."}
          </p>
        </div>
        <PrimaryButton
          onClick={() => setCreating(true)}
          disabled={!app}
          title={app ? undefined : "Somente leitura no demo"}
          className={app ? "" : "cursor-not-allowed opacity-60"}
        >
          <Plus className="size-4" strokeWidth={2.4} /> Adicionar
        </PrimaryButton>
      </header>

      <div className="space-y-3">
        <FilterPills
          label="Classe"
          value={assetClass}
          onChange={setAssetClass}
          options={[
            { key: "todas", label: "Todas" },
            ...CLASSES.map((k) => ({ key: k, label: tokens.assetClass[k].label, color: tokens.assetClass[k].color })),
          ]}
        />
        {brokers.length > 1 ? (
          <FilterPills
            label="Corretora"
            value={broker}
            onChange={setBroker}
            options={[{ key: "todas", label: "Todas as corretoras" }, ...brokers.map(([id, name]) => ({ key: id, label: name }))]}
          />
        ) : null}
      </div>

      {positions.data && positions.data.length === 0 ? (
        <GlassCard lift={false} className="text-center">
          <p className="text-[15px] font-medium">Nenhuma posição ainda.</p>
          <p className="mt-1 text-[14px] text-muted">As posições aparecem depois do primeiro lançamento e do próximo fechamento.</p>
        </GlassCard>
      ) : null}

      <section aria-label="Classes" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {positions.isLoading
          ? [0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-[150px] rounded-[22px]" />)
          : summaries.map((c) => {
              const meta = tokens.assetClass[c.key];
              const selected = assetClass === c.key;
              const quota = broker === "todas" ? twr(c.key) : undefined;
              return (
                <GlassCard
                  key={c.key}
                  tint={meta.color}
                  role="button"
                  tabIndex={0}
                  aria-pressed={selected}
                  onClick={() => setAssetClass(selected ? "todas" : c.key)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setAssetClass(selected ? "todas" : c.key);
                  }}
                  className={`cursor-pointer ${selected ? "ring-2 ring-white/70" : ""}`}
                >
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-2 text-[14px] font-medium">
                      <span className="size-2.5 rounded-full" style={{ background: meta.color }} />
                      {meta.label}
                    </span>
                    <span data-num className="text-[12px] text-muted">{formatPct(total ? c.value / total : 0)}</span>
                  </div>
                  <div data-num className="mt-3 text-[22px] font-semibold tracking-tight">{formatBRL(c.value)}</div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-subtle">
                    {c.cost > 0 ? (
                      <DeltaBadge value={c.value / c.cost - 1}>{formatPctSigned(c.value / c.cost - 1)}</DeltaBadge>
                    ) : null}
                    <span>
                      {c.count} {c.count === 1 ? "ativo" : "ativos"}
                      {c.key === "renda_fixa" ? " · valor bruto" : ""}
                    </span>
                  </div>
                  {quota !== undefined ? (
                    <div className="mt-2 text-[12px] text-subtle">
                      Rentabilidade desde o início: <span data-num className="text-ink">{formatPctSigned(quota - 1)}</span>
                    </div>
                  ) : null}
                </GlassCard>
              );
            })}
      </section>

      {traded.length ? (
        <GlassCard lift={false}>
          <CardHeader
            title={assetClass === "todas" || assetClass === "renda_fixa" ? "Ativos" : tokens.assetClass[assetClass].label}
            subtitle="Preço médio com taxas; rentabilidade sobre o custo da posição"
          />
          <TradedTable rows={traded} />
        </GlassCard>
      ) : null}
      {fixed.length ? (
        <GlassCard lift={false}>
          <CardHeader title="Renda fixa" subtitle="Valor bruto, antes do IR; rende pelo CDI diário" />
          <FixedIncomeTable rows={fixed} />
        </GlassCard>
      ) : null}

      {app ? <ManualEntryDialog open={creating} onClose={() => setCreating(false)} /> : null}
    </motion.div>
  );
}
