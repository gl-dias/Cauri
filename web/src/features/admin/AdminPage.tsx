import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, UserPlus } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";

import { ApiError, type AllowlistEntry } from "@/data/api";
import { useAppSource } from "@/data/context";
import type { JobRun, JobSource } from "@/data/types";
import { formatDate } from "@/lib/format";
import { GlassButton, PrimaryButton } from "@/ui/controls";
import { Dialog } from "@/ui/Dialog";
import { Field, SelectInput, TextInput } from "@/ui/forms";
import { CardHeader, GlassCard } from "@/ui/GlassCard";
import { pageVariants, staticVariants } from "@/ui/motion";
import { Skeleton } from "@/ui/viz";

const STATUS_STYLE: Record<string, string> = {
  ok: "text-gain [background:color-mix(in_srgb,var(--cauri-gain)_16%,rgba(0,0,0,0.74))]",
  partial: "text-gold [background:color-mix(in_srgb,var(--cauri-gold)_14%,rgba(0,0,0,0.74))]",
  quota_exceeded: "text-gold [background:color-mix(in_srgb,var(--cauri-gold)_14%,rgba(0,0,0,0.74))]",
  failed: "text-loss [background:color-mix(in_srgb,var(--cauri-loss)_16%,rgba(0,0,0,0.74))]",
  running: "bg-black/40 text-muted",
  skipped: "bg-black/40 text-muted",
};
const STATUS_LABEL: Record<string, string> = {
  ok: "ok",
  partial: "parcial",
  quota_exceeded: "cota esgotada",
  failed: "falhou",
  running: "rodando",
  skipped: "pulada",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_STYLE[status] ?? "bg-white/10"}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function dateTime(iso: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "America/Sao_Paulo",
  }).format(new Date(iso));
}

function AllowlistPanel() {
  const app = useAppSource();
  const client = useQueryClient();
  const list = useQuery({ queryKey: ["app", "allowlist"], queryFn: () => app!.api.allowlist.list(), enabled: Boolean(app) });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<AllowlistEntry | null>(null);
  const [busy, setBusy] = useState(false);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await client.invalidateQueries({ queryKey: ["app", "allowlist"] });
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Sem conexão com a API.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <GlassCard lift={false}>
      <CardHeader title="Convidados" subtitle="Só quem está nesta lista consegue entrar. Remover corta o acesso na hora." />
      <form
        className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-[1.6fr_0.8fr_1.2fr_auto] sm:items-end"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await act(() => app!.api.allowlist.add(email, role, note))) {
            setEmail("");
            setNote("");
            setRole("user");
          }
        }}
      >
        <Field label="E-mail" htmlFor="adm-email">
          <TextInput id="adm-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="amigo@exemplo.com" />
        </Field>
        <Field label="Papel" htmlFor="adm-papel">
          <SelectInput id="adm-papel" value={role} onChange={(e) => setRole(e.target.value as "user" | "admin")}>
            <option value="user">Usuário</option>
            <option value="admin">Admin</option>
          </SelectInput>
        </Field>
        <Field label="Observação" htmlFor="adm-obs">
          <TextInput id="adm-obs" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Opcional" />
        </Field>
        <PrimaryButton type="submit" disabled={busy || !email}>
          <UserPlus className="size-4" /> Convidar
        </PrimaryButton>
      </form>
      {error ? (
        <p role="alert" className="mb-4 rounded-[14px] border border-loss/40 bg-loss/10 px-3 py-2 text-[13px]">
          {error}
        </p>
      ) : null}

      {list.isLoading ? (
        <Skeleton className="h-40" />
      ) : (
        <ul className="divide-y divide-white/[0.06]">
          {list.data?.map((entry) => (
            <li key={entry.email} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:gap-4">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px] font-medium">{entry.email}</div>
                <div className="text-[12px] text-subtle">
                  desde {formatDate(entry.added_at)}
                  {entry.note ? ` · ${entry.note}` : ""}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <SelectInput
                  aria-label={`Papel de ${entry.email}`}
                  value={entry.role}
                  disabled={busy}
                  className="h-9 w-[128px] text-[13px]"
                  onChange={(e) => act(() => app!.api.allowlist.update(entry.email, e.target.value as "user" | "admin"))}
                >
                  <option value="user">Usuário</option>
                  <option value="admin">Admin</option>
                </SelectInput>
                <button
                  type="button"
                  aria-label={`Remover ${entry.email}`}
                  onClick={() => setRemoving(entry)}
                  className="grid size-9 place-items-center rounded-full text-muted hover:bg-loss/15 hover:text-loss"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog
        open={Boolean(removing)}
        onClose={() => setRemoving(null)}
        title="Remover convidado"
        footer={
          <>
            <GlassButton onClick={() => setRemoving(null)}>Cancelar</GlassButton>
            <button
              type="button"
              disabled={busy}
              onClick={async () => {
                if (removing && (await act(() => app!.api.allowlist.remove(removing.email)))) setRemoving(null);
              }}
              className="inline-flex h-11 items-center rounded-full bg-loss px-5 text-[14px] font-semibold text-on-light disabled:opacity-50"
            >
              Remover acesso
            </button>
          </>
        }
      >
        <p className="text-[14px] text-muted">
          <span className="font-medium text-ink">{removing?.email}</span> perde o acesso imediatamente. Os dados dessa pessoa
          continuam guardados e voltam a aparecer se ela for convidada de novo.
        </p>
      </Dialog>
    </GlassCard>
  );
}

function JobsPanel() {
  const app = useAppSource();
  const runs = useQuery({ queryKey: ["app", "job_runs"], queryFn: () => app!.jobRuns(8), enabled: Boolean(app) });
  const ids = runs.data?.map((r) => r.id) ?? [];
  const sources = useQuery({
    queryKey: ["app", "job_sources", ids],
    queryFn: () => app!.jobSources(ids),
    enabled: Boolean(app) && ids.length > 0,
  });
  const byRun = (run: JobRun) => (sources.data ?? []).filter((s: JobSource) => s.run_id === run.id);
  return (
    <GlassCard lift={false}>
      <CardHeader title="Execuções dos jobs" subtitle="Fechamento diário (18h30 e 19h30) e histórico, com o status de cada fonte" />
      {runs.isLoading ? (
        <Skeleton className="h-40" />
      ) : runs.data?.length ? (
        <ul className="space-y-2.5">
          {runs.data.map((run) => (
            <li key={run.id} className="glass-inset space-y-2 p-3.5">
              <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
                <span className="font-medium">
                  {run.job === "daily" ? "Fechamento diário" : run.job === "backfill" ? "Histórico" : run.job}
                  <span className="ml-2 text-subtle">{run.trigger === "cron" ? "agendado" : "manual"}</span>
                </span>
                <span className="flex items-center gap-2 text-subtle">
                  <span data-num>{dateTime(run.started_at)}</span>
                  <StatusBadge status={run.status} />
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {byRun(run).map((s) => (
                  <span key={s.source} title={s.error_sample ?? undefined} className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[11px] text-muted">
                    {s.source} <StatusBadge status={s.status} />
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[14px] text-muted">Nenhuma execução registrada ainda.</p>
      )}
    </GlassCard>
  );
}

export function AdminPage() {
  const reduced = useReducedMotion();
  return (
    <motion.div variants={reduced ? staticVariants : pageVariants} initial="hidden" animate="show" className="space-y-5 sm:space-y-6">
      <header>
        <h1 className="text-[28px] font-semibold tracking-tight sm:text-[34px]">Admin</h1>
        <p className="mt-1 text-[14px] text-muted">Quem entra no Cauri e como andam os jobs de mercado.</p>
      </header>
      <div className="grid grid-cols-1 gap-5 sm:gap-6 xl:grid-cols-12">
        <div className="min-w-0 xl:col-span-7">
          <AllowlistPanel />
        </div>
        <div className="min-w-0 xl:col-span-5">
          <JobsPanel />
        </div>
      </div>
    </motion.div>
  );
}
