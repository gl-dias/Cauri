import { Coins, Download, Scale, TrendingUp, Wallet } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useMemo, useState } from "react";

import { useAgenda, useBuckets, useGoal, useMe, usePortfolioDaily, useRecentMovements, useSource } from "@/data/context";
import { computeKpis, evolution, PERIODS, slicePeriod, type Period } from "@/data/metrics";
import type { PortfolioDay } from "@/data/types";
import {
  formatBRL,
  formatBRLSigned,
  formatDate,
  formatPct,
  formatPctSigned,
  formatPP,
  greeting,
} from "@/lib/format";
import { tokens } from "@/theme/tokens";
import { DeltaBadge, GlassButton, SegmentedControl } from "@/ui/controls";
import { KpiCard } from "@/ui/KpiCard";
import { pageVariants, staticVariants } from "@/ui/motion";
import { AnimatedNumber, Skeleton } from "@/ui/viz";

import { AgendaPanel, AllocationPanel, EvolutionPanel, GoalPanel, RecentMovementsPanel } from "./sections";

function exportCsv(days: PortfolioDay[], period: Period) {
  const { rows } = slicePeriod(days, period);
  const header = "data;patrimonio;aportes_liquidos;proventos;cota;cdi_acumulado;linha_cdi";
  const lines = rows.map((d) =>
    [d.snap_date, d.market_value, d.net_flows, d.income, d.quota_value, d.cdi_index, d.cdi_equivalent ?? ""]
      .map((v) => String(v).replace(".", ","))
      .join(";"),
  );
  const blob = new Blob([`﻿${header}\n${lines.join("\n")}\n`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `cauri-evolucao-${period}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function HomePage() {
  const reduced = useReducedMotion();
  const source = useSource();
  // Demo abre em "Tudo" (a carteira fictícia tem 12 meses); o app abre no ano corrente.
  const [period, setPeriod] = useState<Period>(source.mode === "demo" ? "tudo" : "ano");
  const me = useMe();
  const daily = usePortfolioDaily();
  const agenda = useAgenda();
  const recent = useRecentMovements(6);
  const goal = useGoal();
  const lastDay = daily.data?.at(-1);
  const classes = useBuckets(lastDay?.snap_date, "class");

  const kpis = useMemo(() => (daily.data ? computeKpis(daily.data, period) : null), [daily.data, period]);
  const points = useMemo(() => (daily.data ? evolution(daily.data, period) : undefined), [daily.data, period]);
  const firstName = me.data?.display_name.split(/\s+/)[0] ?? "";

  return (
    <motion.div
      variants={reduced ? staticVariants : pageVariants}
      initial="hidden"
      animate="show"
      className="space-y-5 sm:space-y-6"
    >
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight sm:text-[34px]">
            {greeting()}
            {firstName ? `, ${firstName}` : ""}
          </h1>
          <p className="mt-1 text-[14px] text-muted">
            {lastDay ? (
              <>
                Preços de fechamento de {formatDate(lastDay.snap_date)}
                {lastDay.stale_count > 0 ? ` · ${lastDay.stale_count} ativo(s) sem atualização` : ""}
              </>
            ) : (
              "Carregando a carteira..."
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <SegmentedControl label="Período" options={PERIODS} value={period} onChange={setPeriod} />
          <GlassButton onClick={() => daily.data && exportCsv(daily.data, period)} disabled={!daily.data}>
            <Download className="size-4" strokeWidth={2} /> Exportar
          </GlassButton>
        </div>
      </header>

      <section
        aria-label="Indicadores"
        className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-4 overflow-x-auto px-4 pb-1 md:mx-0 md:grid md:grid-cols-2 md:overflow-visible md:px-0 xl:grid-cols-4"
      >
        {kpis ? (
          <>
            <KpiCard
              icon={Wallet}
              color={tokens.assetClass.acao.color}
              label="Patrimônio total"
              value={<AnimatedNumber value={kpis.marketValue} format={formatBRL} />}
              badge={
                kpis.marketValueChange !== null ? (
                  <DeltaBadge value={kpis.marketValueChange}>{formatPctSigned(kpis.marketValueChange)}</DeltaBadge>
                ) : (
                  <DeltaBadge tone="neutral">desde {formatDate(kpis.since)}</DeltaBadge>
                )
              }
              footnote={kpis.marketValueChange !== null ? "com aportes" : undefined}
              spark={kpis.spark.marketValue}
            />
            <KpiCard
              icon={TrendingUp}
              color={kpis.twr >= 0 ? tokens.color.gain : tokens.color.loss}
              label="Rentabilidade no período"
              value={<AnimatedNumber value={kpis.twr} format={formatPctSigned} />}
              badge={<DeltaBadge value={kpis.result}>{formatBRLSigned(kpis.result)}</DeltaBadge>}
              footnote="método de cotas"
              spark={kpis.spark.twr}
            />
            <KpiCard
              icon={Scale}
              color={kpis.vsCdi >= 0 ? tokens.color.gain : tokens.color.loss}
              label="Resultado vs CDI"
              value={<AnimatedNumber value={kpis.vsCdi} format={formatPP} />}
              badge={<DeltaBadge tone="neutral">CDI {formatPct(kpis.cdi)}</DeltaBadge>}
              footnote={`carteira ${formatPctSigned(kpis.twr)}`}
              spark={kpis.spark.vsCdi}
            />
            <KpiCard
              icon={Coins}
              color={tokens.color.gold}
              label="Proventos no período"
              value={<AnimatedNumber value={kpis.income} format={formatBRL} />}
              badge={<DeltaBadge tone="neutral">{kpis.incomeCount} pagamento(s)</DeltaBadge>}
              spark={kpis.spark.income}
            />
          </>
        ) : (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[214px] min-w-[260px] rounded-[22px] md:min-w-0" />)
        )}
      </section>

      <div className="grid grid-cols-1 gap-5 sm:gap-6 xl:grid-cols-12">
        <div className="min-w-0 xl:col-span-8">
          <EvolutionPanel points={points} period={period} />
        </div>
        <div className="min-w-0 xl:col-span-4">
          <AgendaPanel items={agenda.data} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 sm:gap-6 md:grid-cols-2 xl:grid-cols-12">
        <div className="md:col-span-2 xl:col-span-5">
          <RecentMovementsPanel items={recent.data} />
        </div>
        <div className="xl:col-span-4">
          <AllocationPanel buckets={classes.data} />
        </div>
        <div className="xl:col-span-3">
          <GoalPanel goal={goal.data} current={lastDay?.market_value} />
        </div>
      </div>
    </motion.div>
  );
}
