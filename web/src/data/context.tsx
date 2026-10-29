import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";

import type { PortfolioReader } from "./source";
import type { Bucket } from "./types";

const SourceContext = createContext<PortfolioReader | null>(null);

export function SourceProvider({ source, children }: { source: PortfolioReader; children: ReactNode }) {
  return <SourceContext.Provider value={source}>{children}</SourceContext.Provider>;
}

export function useSource(): PortfolioReader {
  const source = useContext(SourceContext);
  if (!source) throw new Error("SourceProvider ausente");
  return source;
}

/** Hoje em Brasília, AAAA-MM-DD. */
export function todaySP(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
}

export const useMe = () => {
  const s = useSource();
  return useQuery({ queryKey: [s.mode, "me"], queryFn: () => s.me() });
};

export const usePortfolioDaily = () => {
  const s = useSource();
  return useQuery({ queryKey: [s.mode, "portfolio_daily"], queryFn: () => s.portfolioDaily() });
};

export const usePositions = () => {
  const s = useSource();
  return useQuery({ queryKey: [s.mode, "positions"], queryFn: () => s.positions() });
};

export const useBuckets = (day: string | undefined, kind: Bucket["bucket_kind"]) => {
  const s = useSource();
  return useQuery({
    queryKey: [s.mode, "buckets", day, kind],
    queryFn: () => s.buckets(day ?? "", kind),
    enabled: Boolean(day),
  });
};

export const useAgenda = () => {
  const s = useSource();
  return useQuery({ queryKey: [s.mode, "agenda"], queryFn: () => s.agenda() });
};

export const useRecentMovements = (limit = 6) => {
  const s = useSource();
  return useQuery({
    queryKey: [s.mode, "recent", limit],
    queryFn: () => s.recentMovements(limit, todaySP()),
  });
};

export const useGoal = () => {
  const s = useSource();
  return useQuery({ queryKey: [s.mode, "goal"], queryFn: () => s.goal() });
};
