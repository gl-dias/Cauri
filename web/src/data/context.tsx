import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, type ReactNode } from "react";

import type { AnySource, AppSource } from "./source";
import type { Bucket, LedgerFilter } from "./types";

const SourceContext = createContext<AnySource | null>(null);

export function SourceProvider({ source, children }: { source: AnySource; children: ReactNode }) {
  return <SourceContext.Provider value={source}>{children}</SourceContext.Provider>;
}

export function useSource(): AnySource {
  const source = useContext(SourceContext);
  if (!source) throw new Error("SourceProvider ausente");
  return source;
}

/** Fonte com escrita, ou null no /demo (somente leitura). */
export function useAppSource(): AppSource | null {
  const source = useSource();
  return source.mode === "app" ? source : null;
}

/** Hoje em Brasília, AAAA-MM-DD. */
export function todaySP(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());
}

export const useMe = () => {
  const s = useSource();
  return useQuery({ queryKey: [s.mode, "me"], queryFn: () => s.me(), retry: false });
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
  return useQuery({ queryKey: [s.mode, "recent", limit], queryFn: () => s.recentMovements(limit, todaySP()) });
};

export const PAGE_SIZE = 25;

export const useMovements = (filter: LedgerFilter) => {
  const s = useSource();
  return useInfiniteQuery({
    queryKey: [s.mode, "movements", filter],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => s.movements(filter, pageParam, PAGE_SIZE),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((sum, p) => sum + p.rows.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
  });
};

export const useGoal = () => {
  const s = useSource();
  return useQuery({ queryKey: [s.mode, "goal"], queryFn: () => s.goal() });
};

export const useBrokers = () => {
  const s = useAppSource();
  return useQuery({
    queryKey: ["app", "brokers"],
    queryFn: () => (s ? s.brokers() : Promise.resolve([])),
    enabled: Boolean(s),
    staleTime: Infinity,
  });
};

/** Depois de uma gravação: tudo que deriva do ledger é recarregado. */
export function useRefreshAfterWrite() {
  const client = useQueryClient();
  return useCallback(() => client.invalidateQueries({ queryKey: ["app"] }), [client]);
}
