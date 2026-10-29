import { Eye, Pencil, Plus, Search, SlidersHorizontal, Trash2 } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useDeferredValue, useMemo, useState } from "react";

import { useAppSource, useMovements } from "@/data/context";
import type { LedgerFilter, MovementRow, MovementType, Origin } from "@/data/types";
import { formatBRL, formatDate, formatQuantity } from "@/lib/format";
import { assetInitials, movementValue, originalText, originText, ORIGIN_LABEL, TYPE_LABEL } from "@/lib/movements";
import { tokens, type AssetClassKey } from "@/theme/tokens";
import { GlassButton, PrimaryButton } from "@/ui/controls";
import { GlassCard } from "@/ui/GlassCard";
import { SelectInput, TextInput } from "@/ui/forms";
import { pageVariants, staticVariants } from "@/ui/motion";
import { AssetAvatar, Skeleton } from "@/ui/viz";

import { EditMovementDialog, ManualEntryDialog, VoidMovementDialog } from "./dialogs";

const classColor = (key: string) => tokens.assetClass[key as AssetClassKey]?.color ?? tokens.color.accent;

function OriginBadge({ m }: { m: MovementRow }) {
  return (
    <span className="inline-flex shrink-0 rounded-full border border-white/15 bg-black/25 px-2 py-0.5 text-[11px] font-medium text-muted">
      {originText(m)}
    </span>
  );
}

function AssetCell({ m }: { m: MovementRow }) {
  const color = classColor(m.asset_class);
  return (
    <div className="flex min-w-0 items-center gap-3">
      <AssetAvatar initials={assetInitials(m.asset_label)} color={color} />
      <div className="min-w-0">
        <div className={`truncate font-medium ${m.voided_at ? "text-subtle line-through" : ""}`}>{m.asset_label}</div>
        {m.asset_name ? <div className="truncate text-[12px] text-subtle">{m.asset_name}</div> : null}
      </div>
    </div>
  );
}

function valueText(m: MovementRow): string {
  const v = movementValue(m);
  if (v !== null) return formatBRL(v);
  if (m.factor !== null) return `fator ${formatQuantity(m.factor)}`;
  return "";
}

export function LedgerPage() {
  const reduced = useReducedMotion();
  const app = useAppSource();
  const [search, setSearch] = useState("");
  const [type, setType] = useState<"" | MovementType>("");
  const [assetClass, setAssetClass] = useState<"" | AssetClassKey>("");
  const [origin, setOrigin] = useState<"" | Origin>("");
  const [showVoided, setShowVoided] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<MovementRow | null>(null);
  const [voiding, setVoiding] = useState<MovementRow | null>(null);
  const deferredSearch = useDeferredValue(search);

  const filter = useMemo<LedgerFilter>(
    () => ({
      search: deferredSearch || undefined,
      type: type || undefined,
      assetClass: assetClass || undefined,
      origin: origin || undefined,
      showVoided,
    }),
    [deferredSearch, type, assetClass, origin, showVoided],
  );
  const query = useMovements(filter);
  const rows = query.data?.pages.flatMap((p) => p.rows) ?? [];
  const activeFilters = [type, assetClass, origin].filter(Boolean).length + (showVoided ? 1 : 0);
  const total = query.data?.pages[0]?.total ?? 0;

  return (
    <motion.div variants={reduced ? staticVariants : pageVariants} initial="hidden" animate="show" className="space-y-5 sm:space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight sm:text-[34px]">Lançamentos</h1>
          <p className="mt-1 text-[14px] text-muted">
            {query.data ? `${total} movimentações` : "Carregando..."}
            {app ? "" : " · somente leitura no demo"}
          </p>
        </div>
        {app ? (
          <PrimaryButton onClick={() => setCreating(true)}>
            <Plus className="size-4" strokeWidth={2.4} /> Novo lançamento
          </PrimaryButton>
        ) : null}
      </header>

      <GlassCard lift={false} className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr_auto]">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-subtle" />
              <TextInput aria-label="Buscar ativo" placeholder="Buscar ativo" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-10" />
            </div>
            {/* No celular, os outros filtros ficam atrás deste botão. */}
            <GlassButton
              className="shrink-0 sm:hidden"
              aria-expanded={filtersOpen}
              onClick={() => setFiltersOpen((v) => !v)}
            >
              <SlidersHorizontal className="size-4" /> Filtros{activeFilters ? ` (${activeFilters})` : ""}
            </GlassButton>
          </div>
          <div className={`${filtersOpen ? "grid" : "hidden"} grid-cols-1 gap-3 sm:contents`}>
          <SelectInput aria-label="Tipo" value={type} onChange={(e) => setType(e.target.value as typeof type)}>
            <option value="">Todos os tipos</option>
            {(Object.keys(TYPE_LABEL) as MovementType[]).map((k) => (
              <option key={k} value={k}>{TYPE_LABEL[k]}</option>
            ))}
          </SelectInput>
          <SelectInput aria-label="Classe" value={assetClass} onChange={(e) => setAssetClass(e.target.value as typeof assetClass)}>
            <option value="">Todas as classes</option>
            {(Object.keys(tokens.assetClass) as AssetClassKey[]).map((k) => (
              <option key={k} value={k}>{tokens.assetClass[k].label}</option>
            ))}
          </SelectInput>
          <SelectInput aria-label="Origem" value={origin} onChange={(e) => setOrigin(e.target.value as typeof origin)}>
            <option value="">Todas as origens</option>
            {(Object.keys(ORIGIN_LABEL) as Origin[]).map((k) => (
              <option key={k} value={k}>{ORIGIN_LABEL[k]}</option>
            ))}
          </SelectInput>
          <label className="flex h-11 cursor-pointer items-center gap-2 rounded-[14px] border border-white/15 bg-black/25 px-3.5 text-[13px] text-muted">
            <input type="checkbox" checked={showVoided} onChange={(e) => setShowVoided(e.target.checked)} className="size-4 accent-[var(--cauri-accent)]" />
            <Eye className="size-4" /> Removidas
          </label>
          </div>
        </div>

        {query.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="py-10 text-center text-[14px] text-muted">Nenhuma movimentação com esses filtros.</p>
        ) : (
          <>
            {/* Desktop: tabela de vidro */}
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[860px] text-left text-[13px]">
                <thead>
                  <tr className="border-b border-white/10 text-[12px] text-subtle">
                    <th className="py-2.5 pr-3 font-medium">Data</th>
                    <th className="py-2.5 pr-3 font-medium">Ativo</th>
                    <th className="py-2.5 pr-3 font-medium">Tipo</th>
                    <th className="py-2.5 pr-3 text-right font-medium">Quantidade</th>
                    <th className="py-2.5 pr-3 text-right font-medium">Preço</th>
                    <th className="py-2.5 pr-3 text-right font-medium">Valor</th>
                    <th className="py-2.5 pr-3 font-medium">Corretora</th>
                    <th className="py-2.5 pr-3 font-medium">Origem</th>
                    {app ? <th className="py-2.5 font-medium"><span className="sr-only">Ações</span></th> : null}
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.06]">
                  {rows.map((m) => (
                    <tr key={m.id} className={`align-middle ${m.voided_at ? "opacity-70" : ""}`}>
                      <td data-num className="py-2.5 pr-3 whitespace-nowrap text-muted">{formatDate(m.trade_date)}</td>
                      <td className="max-w-[240px] py-2.5 pr-3"><AssetCell m={m} /></td>
                      <td className="py-2.5 pr-3 whitespace-nowrap">
                        {TYPE_LABEL[m.type]}
                        {m.voided_at ? <span className="ml-2 rounded-full bg-loss/15 px-2 py-0.5 text-[11px] text-loss">removida</span> : null}
                      </td>
                      <td data-num className="py-2.5 pr-3 text-right">{m.quantity !== null ? formatQuantity(m.quantity) : ""}</td>
                      <td data-num className="py-2.5 pr-3 text-right">{m.unit_price !== null ? formatBRL(m.unit_price) : ""}</td>
                      <td data-num className="py-2.5 pr-3 text-right font-medium">
                        {valueText(m)}
                        {originalText(m) ? <div className="text-[11px] font-normal text-muted">{originalText(m)}</div> : null}
                      </td>
                      <td className="py-2.5 pr-3 whitespace-nowrap text-muted">{m.broker_name}</td>
                      <td className="py-2.5 pr-3"><OriginBadge m={m} /></td>
                      {app ? (
                        <td className="py-2.5 whitespace-nowrap">
                          {m.voided_at ? null : (
                            <div className="flex justify-end gap-1">
                              <button type="button" aria-label={`Editar ${m.asset_label}`} onClick={() => setEditing(m)} className="grid size-8 place-items-center rounded-full text-muted hover:bg-white/10 hover:text-ink">
                                <Pencil className="size-4" />
                              </button>
                              <button type="button" aria-label={`Remover ${m.asset_label}`} onClick={() => setVoiding(m)} className="grid size-8 place-items-center rounded-full text-muted hover:bg-loss/15 hover:text-loss">
                                <Trash2 className="size-4" />
                              </button>
                            </div>
                          )}
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Celular: cards */}
            <ul className="space-y-2.5 md:hidden">
              {rows.map((m) => (
                <li key={m.id} className="glass-inset space-y-2 p-3.5">
                  <div className="flex items-start justify-between gap-3">
                    <AssetCell m={m} />
                    <OriginBadge m={m} />
                  </div>
                  <div className="flex items-end justify-between gap-3 text-[13px]">
                    <div className="text-muted">
                      {TYPE_LABEL[m.type]} · <span data-num>{formatDate(m.trade_date)}</span>
                      {m.quantity !== null ? <> · <span data-num>{formatQuantity(m.quantity)}</span></> : null}
                      {m.voided_at ? <span className="ml-1 text-loss">· removida</span> : null}
                    </div>
                    <div data-num className="shrink-0 font-semibold">{valueText(m)}</div>
                  </div>
                  {originalText(m) ? <div data-num className="text-right text-[12px] text-muted">{originalText(m)}</div> : null}
                  {app && !m.voided_at ? (
                    <div className="flex gap-2 pt-1">
                      <GlassButton className="h-9 px-3 text-[13px]" onClick={() => setEditing(m)}><Pencil className="size-3.5" /> Editar</GlassButton>
                      <GlassButton className="h-9 px-3 text-[13px]" onClick={() => setVoiding(m)}><Trash2 className="size-3.5" /> Remover</GlassButton>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>

            {query.hasNextPage ? (
              <div className="flex justify-center pt-2">
                <GlassButton onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage}>
                  {query.isFetchingNextPage ? "Carregando..." : `Carregar mais (${rows.length} de ${total})`}
                </GlassButton>
              </div>
            ) : null}
          </>
        )}
      </GlassCard>

      {app ? (
        <>
          <ManualEntryDialog open={creating} onClose={() => setCreating(false)} />
          <EditMovementDialog movement={editing} onClose={() => setEditing(null)} />
          <VoidMovementDialog movement={voiding} onClose={() => setVoiding(null)} />
        </>
      ) : null}
    </motion.div>
  );
}
