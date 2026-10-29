import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileSpreadsheet, History, ShieldCheck, Trash2, Upload, X } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useMemo, useRef, useState, type DragEvent } from "react";
import { Link } from "react-router";

import {
  ApiError,
  type ImportBatch,
  type ImportCommitOut,
  type ImportDecision,
  type ImportPreview,
  type ImportProfile,
  type ImportRow,
  type ImportRowStatus,
  type ProfileField,
  type ProfileOptions,
} from "@/data/api";
import { useAppSource, useBrokers, useRefreshAfterWrite } from "@/data/context";
import type { AppSource } from "@/data/source";
import { formatBRL, formatDate, formatQuantity } from "@/lib/format";
import { INCOME_LABEL, originalText, TYPE_LABEL } from "@/lib/movements";
import { GlassButton, PrimaryButton } from "@/ui/controls";
import { Dialog } from "@/ui/Dialog";
import { Field, FilterPills, SelectInput, TextInput } from "@/ui/forms";
import { CardHeader, GlassCard } from "@/ui/GlassCard";
import { pageVariants, staticVariants } from "@/ui/motion";

import { OpeningSuggestionCard } from "@/features/shared/OpeningSuggestionCard";

import { countToImport, initialDecisions } from "./decisions";
import { FIELDS, guessMapping, missingForProfile } from "./mapping";
import { SAMPLE_BATCH, SAMPLE_FILENAMES } from "./sample";

const STATUS_LABEL: Record<ImportRowStatus, string> = {
  ok: "pronta",
  possible_duplicate: "possível duplicada",
  already_imported: "já importada",
  error: "com erro",
  ignored: "ignorada",
};
const STATUS_STYLE: Record<ImportRowStatus, string> = {
  ok: "text-gain [background:color-mix(in_srgb,var(--cauri-gain)_16%,rgba(0,0,0,0.74))]",
  possible_duplicate: "text-gold [background:color-mix(in_srgb,var(--cauri-gold)_14%,rgba(0,0,0,0.74))]",
  already_imported: "bg-black/45 text-muted",
  error: "text-loss [background:color-mix(in_srgb,var(--cauri-loss)_16%,rgba(0,0,0,0.74))]",
  ignored: "bg-black/45 text-muted",
};
const FILTERS: { key: "todas" | ImportRowStatus; label: string }[] = [
  { key: "todas", label: "Todas" },
  { key: "ok", label: "Prontas" },
  { key: "possible_duplicate", label: "Possíveis duplicadas" },
  { key: "error", label: "Com erro" },
  { key: "already_imported", label: "Já importadas" },
  { key: "ignored", label: "Ignoradas" },
];
const DECISION_LABEL: Record<Exclude<ImportDecision, "import">, string> = {
  keep_existing: "Manter a existente",
  replace: "Substituir pela planilha",
  import_new: "Importar como nova",
};
const PAGE = 60;

export function ImportPage() {
  const reduced = useReducedMotion();
  const app = useAppSource();
  return (
    <motion.div variants={reduced ? staticVariants : pageVariants} initial="hidden" animate="show" className="space-y-5 sm:space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight sm:text-[34px]">Importar</h1>
          <p className="mt-1 text-[14px] text-muted">
            B3, Binance, os templates do Cauri ou qualquer planilha que você mapear{app ? "" : " · vitrine no demo"}
          </p>
        </div>
        <div className="flex gap-2">
          <a href="/templates/cauri-importacao.xlsx" download className="glass-pill inline-flex h-11 items-center gap-2 px-4 text-[14px] font-medium text-ink hover:bg-white/15">
            <Download className="size-4" /> Template bolsa
          </a>
          <a href="/templates/cauri-cripto.xlsx" download className="glass-pill inline-flex h-11 items-center gap-2 px-4 text-[14px] font-medium text-ink hover:bg-white/15">
            <Download className="size-4" /> Template cripto
          </a>
        </div>
      </header>
      {app ? <ImportFlow app={app} /> : <Showcase />}
    </motion.div>
  );
}

/* /demo: vitrine estática, sem nenhuma chamada ao backend ------------------------------ */

function Showcase() {
  const [decisions, setDecisions] = useState(() => initialDecisions(SAMPLE_BATCH));
  return (
    <>
      <GlassCard lift={false}>
        <p className="text-[14px] text-muted">
          Exemplo de pré-visualização com dados inventados. No app, você arrasta os exports da B3, da Binance ou de
          qualquer planilha (o formato novo você mapeia uma vez) e o Cauri mostra o que vai entrar, o que já estava lá e o
          que parece repetido, antes de gravar qualquer coisa. Operações em dólar e stablecoins viram reais pela PTAX.
        </p>
      </GlassCard>
      <PreviewView batch={SAMPLE_BATCH} filenames={SAMPLE_FILENAMES} decisions={decisions} onDecision={(id, d) => setDecisions((s) => ({ ...s, [id]: d }))} />
      <ActionBar count={countToImport(SAMPLE_BATCH, decisions)} disabled hint="Somente leitura no demo" />
    </>
  );
}

/* /app: envio, pré-visualização, decisões e gravação ---------------------------------- */

type Stage =
  | { step: "select" }
  | { step: "preview"; preview: ImportPreview; files: File[] }
  | { step: "done"; result: ImportCommitOut };

function ImportFlow({ app }: { app: AppSource }) {
  const refresh = useRefreshAfterWrite();
  const [stage, setStage] = useState<Stage>({ step: "select" });
  const [files, setFiles] = useState<File[]>([]);
  const [decisions, setDecisions] = useState<Record<string, ImportDecision>>({});
  const recent = useQuery({ queryKey: ["app", "imports"], queryFn: () => app.api.imports.recent() });

  const upload = useMutation({
    mutationFn: (selected: File[]) => app.api.imports.preview(selected),
    onSuccess: (preview, selected) => {
      setStage({ step: "preview", preview, files: selected });
      setDecisions(preview.batch ? initialDecisions(preview.batch) : {});
      window.scrollTo({ top: 0 });
    },
  });
  const commit = useMutation({
    mutationFn: (batch: ImportBatch) => app.api.imports.commit(batch.id, decisions),
    onSuccess: async (result) => {
      setStage({ step: "done", result });
      setFiles([]);
      window.scrollTo({ top: 0 });
      await refresh();
    },
  });
  const discard = useMutation({
    mutationFn: (batch: ImportBatch) => app.api.imports.discard(batch.id),
    onSuccess: () => setStage({ step: "select" }),
  });

  if (stage.step === "done") {
    const r = stage.result;
    return (
      <GlassCard lift={false} className="text-center">
        <CheckCircle2 className="mx-auto mb-3 size-8 text-gain" />
        <h2 className="text-[20px] font-semibold">
          {r.created === 1 ? "1 movimentação importada" : `${r.created} movimentações importadas`}
        </h2>
        <p className="mt-1 text-[14px] text-muted">
          {[r.replaced ? `${r.replaced} substituída(s)` : "", r.skipped ? `${r.skipped} mantida(s) como estavam` : "", r.already_imported ? `${r.already_imported} já estavam lá` : ""]
            .filter(Boolean)
            .join(" · ") || "Tudo certo."}
          {r.snapshots_updated ? "" : " Os gráficos se atualizam no fechamento de hoje."}
        </p>
        <div className="mt-5 flex justify-center gap-2">
          <Link to="/app/lancamentos" className="inline-flex h-11 items-center rounded-full bg-primary px-5 text-[14px] font-semibold text-white hover:bg-primary-hover">
            Ver lançamentos
          </Link>
          <GlassButton onClick={() => setStage({ step: "select" })}>Nova importação</GlassButton>
        </div>
      </GlassCard>
    );
  }

  if (stage.step === "preview") {
    const { preview } = stage;
    const batch = preview.batch;
    const filenames = preview.file_indexes.map((i) => stage.files[i]?.name ?? "");
    const commitError = commit.error instanceof ApiError ? commit.error : null;
    const unreadable = preview.problems.filter((p) => !p.columns?.length);
    const unknown = preview.problems.filter((p) => p.columns?.length);
    return (
      <>
        {unknown.map((p) => (
          <MappingCard
            key={p.index}
            app={app}
            filename={stage.files[p.index]?.name ?? "arquivo"}
            columns={p.columns ?? []}
            busy={upload.isPending}
            onSaved={() => upload.mutate(stage.files)}
          />
        ))}
        {unreadable.length ? (
          <GlassCard lift={false} className="space-y-2">
            <CardHeader title="Arquivos que não entraram" />
            {unreadable.map((p) => (
              <p key={p.index} className="text-[14px]">
                <span className="font-medium">{stage.files[p.index]?.name}</span>
                <span className="text-muted">: {p.message}</span>
              </p>
            ))}
          </GlassCard>
        ) : null}
        {batch ? (
          <>
            {batch.suggestions?.map((s) => (
              <OpeningSuggestionCard
                key={`${s.ticker}-${s.first_shortfall}`}
                suggestion={s}
                onSubmit={async (body) => {
                  const updated = await app.api.imports.addOpening(batch.id, body);
                  setStage({ ...stage, preview: { ...preview, batch: updated } });
                }}
                note="O saldo inicial entra junto com o resto da importação, só quando você confirmar."
              />
            ))}
            <PreviewView batch={batch} filenames={filenames} decisions={decisions} onDecision={(id, d) => setDecisions((s) => ({ ...s, [id]: d }))} />
            {commitError ? (
              <div role="alert" className="glass-card space-y-1 border-loss/40 p-4 text-[14px]">
                <p className="font-semibold">{commitError.message}</p>
                {commitError.body.messages?.slice(1, 6).map((m) => <p key={m} className="text-muted">{m}</p>)}
              </div>
            ) : null}
            <ActionBar
              count={countToImport(batch, decisions)}
              busy={commit.isPending}
              onImport={() => commit.mutate(batch)}
              onDiscard={() => discard.mutate(batch)}
            />
          </>
        ) : (
          <GlassButton onClick={() => setStage({ step: "select" })}>Escolher outros arquivos</GlassButton>
        )}
      </>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-5 sm:gap-6 xl:grid-cols-12">
      <div className="min-w-0 space-y-5 xl:col-span-8">
        <DropZone files={files} onChange={setFiles} />
        {upload.error ? (
          <p role="alert" className="rounded-[14px] border border-loss/40 bg-black/50 px-3 py-2 text-[13px]">
            {upload.error instanceof ApiError ? upload.error.message : "Sem conexão com a API."}
          </p>
        ) : null}
        <div className="flex justify-end">
          <PrimaryButton disabled={!files.length || upload.isPending} onClick={() => upload.mutate(files)} className="disabled:cursor-not-allowed disabled:opacity-60">
            <FileSpreadsheet className="size-4" /> {upload.isPending ? "Lendo os arquivos..." : "Pré-visualizar"}
          </PrimaryButton>
        </div>
      </div>
      <div className="min-w-0 xl:col-span-4">
        <GlassCard lift={false}>
          <CardHeader title="Importações recentes" />
          {recent.data?.length ? (
            <ul className="space-y-2.5">
              {recent.data.map((b) => (
                <li key={b.id} className="glass-inset p-3 text-[13px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{b.status === "committed" ? `${b.imported} importada(s)` : "Pré-visualização aberta"}</span>
                    <span data-num className="text-subtle">{formatDate(b.created_at.slice(0, 10))}</span>
                  </div>
                  <div className="mt-1 text-subtle">{b.labels.join(" · ")}</div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="flex items-center gap-2 text-[14px] text-muted">
              <History className="size-4" /> Nenhuma importação ainda.
            </p>
          )}
        </GlassCard>
        <ProfilesCard app={app} />
        <GlassCard lift={false}>
          <CardHeader title="Templates" subtitle="Para corretoras e exchanges que o Cauri não lê direto" />
          <ul className="space-y-2 text-[14px]">
            {[
              { name: "Bolsa, Tesouro e renda fixa", file: "cauri-importacao" },
              { name: "Cripto", file: "cauri-cripto" },
            ].map((t) => (
              <li key={t.file} className="glass-inset flex items-center justify-between gap-3 px-3.5 py-2.5">
                <span>{t.name}</span>
                <span className="flex gap-3 text-[13px] font-medium">
                  <a href={`/templates/${t.file}.xlsx`} download className="underline underline-offset-2">.xlsx</a>
                  <a href={`/templates/${t.file}.csv`} download className="underline underline-offset-2">.csv</a>
                </span>
              </li>
            ))}
          </ul>
        </GlassCard>
      </div>
    </div>
  );
}

/* Perfis de importação: mapeamento de colunas de arquivos desconhecidos ---------------- */

function ProfilesCard({ app }: { app: AppSource }) {
  const client = useQueryClient();
  const profiles = useQuery({ queryKey: ["app", "import-profiles"], queryFn: () => app.api.imports.profiles.list() });
  const [removing, setRemoving] = useState<ImportProfile | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) => app.api.imports.profiles.remove(id),
    onSuccess: async () => {
      setRemoving(null);
      await client.invalidateQueries({ queryKey: ["app", "import-profiles"] });
    },
  });
  if (!profiles.data?.length) return null;
  return (
    <GlassCard lift={false}>
      <CardHeader title="Perfis de importação" subtitle="Arquivos que você mapeou, reconhecidos pelo cabeçalho" />
      <ul className="space-y-2">
        {profiles.data.map((p) => (
          <li key={p.id} className="glass-inset flex items-center gap-3 px-3.5 py-2.5 text-[13px]">
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{p.name}</div>
              <div className="text-muted">
                {Object.keys(p.mapping).length} colunas
                {p.last_used_at ? ` · usado em ${formatDate(p.last_used_at.slice(0, 10))}` : ""}
              </div>
            </div>
            <button
              type="button"
              aria-label={`Apagar o perfil ${p.name}`}
              onClick={() => setRemoving(p)}
              className="grid size-8 place-items-center rounded-full text-muted hover:bg-loss/15 hover:text-loss"
            >
              <Trash2 className="size-4" />
            </button>
          </li>
        ))}
      </ul>
      <Dialog
        open={Boolean(removing)}
        onClose={() => setRemoving(null)}
        title="Apagar perfil"
        footer={
          <>
            <GlassButton onClick={() => setRemoving(null)}>Cancelar</GlassButton>
            <PrimaryButton disabled={remove.isPending} onClick={() => removing && remove.mutate(removing.id)}>
              Apagar
            </PrimaryButton>
          </>
        }
      >
        <p className="text-[14px] text-muted">
          O perfil <span className="font-medium text-ink">{removing?.name}</span> deixa de reconhecer o arquivo. O que já foi
          importado com ele continua no ledger.
        </p>
      </Dialog>
    </GlassCard>
  );
}

function MappingCard({ app, filename, columns, busy, onSaved }: {
  app: AppSource;
  filename: string;
  columns: string[];
  busy: boolean;
  onSaved: () => void;
}) {
  const client = useQueryClient();
  const brokers = useBrokers();
  const [mapping, setMapping] = useState<Partial<Record<ProfileField, string>>>(() => guessMapping(columns));
  const [brokerId, setBrokerId] = useState("");
  const [name, setName] = useState("");
  const [dateFormat, setDateFormat] = useState<NonNullable<ProfileOptions["date_format"]>>("dd/mm/aaaa");
  const [decimal, setDecimal] = useState<NonNullable<ProfileOptions["decimal"]>>(",");
  const [currency, setCurrency] = useState("BRL");
  const missing = missingForProfile(mapping, brokerId, name);
  const save = useMutation({
    mutationFn: () =>
      app.api.imports.profiles.save(name.trim(), mapping, {
        ...(brokerId ? { broker_id: brokerId } : {}),
        decimal,
        date_format: dateFormat,
        currency,
      }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["app", "import-profiles"] });
      onSaved();
    },
  });
  const id = (key: string) => `map-${filename}-${key}`.replace(/[^\w-]/g, "-");
  return (
    <GlassCard lift={false} className="space-y-5">
      <CardHeader
        title={`Formato novo: ${filename}`}
        subtitle="Diga qual coluna do arquivo é cada campo. O perfil fica salvo e reconhece esse formato sozinho nas próximas vezes."
      />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {FIELDS.map((f) => (
          <Field key={f.key} label={`${f.label}${f.required ? " *" : ""}`} hint={f.hint} htmlFor={id(f.key)}>
            <SelectInput
              id={id(f.key)}
              value={mapping[f.key] ?? ""}
              onChange={(e) => setMapping((m) => ({ ...m, [f.key]: e.target.value || undefined }))}
            >
              <option value="">Não usar</option>
              {columns.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </SelectInput>
          </Field>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Corretora fixa" hint="se o arquivo não tem a coluna" htmlFor={id("broker")}>
          <SelectInput id={id("broker")} value={brokerId} onChange={(e) => {
            setBrokerId(e.target.value);
            const chosen = brokers.data?.find((b) => b.id === e.target.value);
            if (chosen && !name) setName(chosen.name);
          }}>
            <option value="">Nenhuma</option>
            {brokers.data?.map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </SelectInput>
        </Field>
        <Field label="Formato da data" htmlFor={id("date")}>
          <SelectInput id={id("date")} value={dateFormat} onChange={(e) => setDateFormat(e.target.value as typeof dateFormat)}>
            <option value="dd/mm/aaaa">dd/mm/aaaa</option>
            <option value="aaaa-mm-dd">aaaa-mm-dd</option>
            <option value="mm/dd/aaaa">mm/dd/aaaa</option>
          </SelectInput>
        </Field>
        <Field label="Números" htmlFor={id("decimal")}>
          <SelectInput id={id("decimal")} value={decimal} onChange={(e) => setDecimal(e.target.value as typeof decimal)}>
            <option value=",">1.234,56 (vírgula)</option>
            <option value=".">1,234.56 (ponto)</option>
          </SelectInput>
        </Field>
        <Field label="Moeda padrão do preço" htmlFor={id("currency")}>
          <SelectInput id={id("currency")} value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {["BRL", "USD", "USDT", "USDC"].map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </SelectInput>
        </Field>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <Field label="Nome do perfil" htmlFor={id("name")}>
            <TextInput id={id("name")} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Corretora X" maxLength={80} />
          </Field>
        </div>
        <PrimaryButton disabled={missing.length > 0 || save.isPending || busy} onClick={() => save.mutate()} className="disabled:cursor-not-allowed disabled:opacity-60">
          {save.isPending || busy ? "Salvando..." : "Salvar perfil e pré-visualizar"}
        </PrimaryButton>
      </div>
      {missing.length ? <p className="text-[13px] text-muted">Falta: {missing.join(", ")}.</p> : null}
      {save.error ? (
        <p role="alert" className="text-[13px] text-loss">{save.error instanceof ApiError ? save.error.message : "Sem conexão com a API."}</p>
      ) : null}
      <p className="flex items-start gap-2 text-[13px] text-muted">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" />
        O perfil guarda só os nomes das colunas e estas opções. Nada do conteúdo do arquivo.
      </p>
    </GlassCard>
  );
}

function DropZone({ files, onChange }: { files: File[]; onChange: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const add = (list: FileList | null) => {
    if (!list) return;
    const known = new Set(files.map((f) => `${f.name}:${f.size}`));
    onChange([...files, ...Array.from(list).filter((f) => !known.has(`${f.name}:${f.size}`))].slice(0, 10));
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    add(e.dataTransfer.files);
  };
  return (
    <GlassCard lift={false} className="space-y-4">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={`grid place-items-center rounded-[20px] border border-dashed px-4 py-10 text-center transition-colors ${over ? "border-white/60 bg-white/10" : "border-white/25 bg-black/20"}`}
      >
        <Upload className="mb-3 size-7 text-muted" />
        <p className="text-[15px] font-medium">Arraste os arquivos aqui</p>
        <p className="mt-1 text-[13px] text-muted">.xlsx ou .csv, até 10 arquivos de 5 MB</p>
        <GlassButton className="mt-4" onClick={() => input.current?.click()}>
          Escolher arquivos
        </GlassButton>
        <input
          ref={input}
          type="file"
          multiple
          accept=".xlsx,.csv"
          aria-label="Escolher arquivos"
          className="hidden"
          onChange={(e) => {
            add(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {files.length ? (
        <ul className="space-y-2">
          {files.map((f) => (
            <li key={`${f.name}:${f.size}`} className="glass-inset flex items-center gap-3 px-3.5 py-2.5 text-[14px]">
              <FileSpreadsheet className="size-4 shrink-0 text-muted" />
              <span className="min-w-0 flex-1 truncate">{f.name}</span>
              <span data-num className="shrink-0 text-[12px] text-subtle">{Math.max(1, Math.round(f.size / 1024))} KB</span>
              <button
                type="button"
                aria-label={`Tirar ${f.name}`}
                onClick={() => onChange(files.filter((x) => x !== f))}
                className="grid size-8 place-items-center rounded-full text-muted hover:bg-white/10 hover:text-ink"
              >
                <X className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="flex items-start gap-2 text-[13px] text-muted">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" />
        Os arquivos são lidos na hora e não ficam guardados. Só as colunas das movimentações são lidas: CPF e nome nunca
        entram no Cauri.
      </p>
    </GlassCard>
  );
}

/* Pré-visualização (compartilhada pelo app e pela vitrine) ------------------------------ */

function PreviewView({ batch, filenames, decisions, onDecision }: {
  batch: ImportBatch;
  filenames: string[];
  decisions: Record<string, ImportDecision>;
  onDecision: (rowId: string, decision: ImportDecision) => void;
}) {
  const [filter, setFilter] = useState<"todas" | ImportRowStatus>("todas");
  const options = FILTERS.filter((f) => f.key === "todas" || (batch.counts[f.key] ?? 0) > 0).map((f) => ({
    key: f.key,
    label: f.key === "todas" ? `Todas (${total(batch.counts)})` : `${f.label} (${batch.counts[f.key]})`,
  }));
  return (
    <div className="space-y-5">
      {batch.warnings.map((w) => (
        <p key={w} className="glass-card px-4 py-3 text-[14px] text-gold">{w}</p>
      ))}
      <FilterPills label="Filtrar linhas" options={options} value={filter} onChange={setFilter} />
      {batch.files.map((file, i) => (
        <FileSection key={file.id} title={filenames[i] || file.label} subtitle={filenames[i] ? file.label : undefined} rows={file.rows} filter={filter} decisions={decisions} onDecision={onDecision} />
      ))}
    </div>
  );
}

function total(counts: ImportBatch["counts"]): number {
  return Object.values(counts).reduce((a, b) => a + (b ?? 0), 0);
}

function FileSection({ title, subtitle, rows, filter, decisions, onDecision }: {
  title: string;
  subtitle?: string;
  rows: ImportRow[];
  filter: "todas" | ImportRowStatus;
  decisions: Record<string, ImportDecision>;
  onDecision: (rowId: string, decision: ImportDecision) => void;
}) {
  const [limit, setLimit] = useState(PAGE);
  const visible = useMemo(() => rows.filter((r) => filter === "todas" || r.status === filter), [rows, filter]);
  if (!visible.length) return null;
  const shown = visible.slice(0, limit);
  return (
    <GlassCard lift={false}>
      <CardHeader title={title} subtitle={`${subtitle ? `${subtitle} · ` : ""}${rows.length === 1 ? "1 linha" : `${rows.length} linhas`}`} />
      {/* Desktop: tabela */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[900px] text-left text-[13px]">
          <thead>
            <tr className="border-b border-white/10 text-[12px] text-muted">
              <th className="py-2.5 pr-3 font-medium">Linha</th>
              <th className="py-2.5 pr-3 font-medium">Situação</th>
              <th className="py-2.5 pr-3 font-medium">Data</th>
              <th className="py-2.5 pr-3 font-medium">Movimentação</th>
              <th className="py-2.5 pr-3 font-medium">Ativo</th>
              <th className="py-2.5 pr-3 text-right font-medium">Quantidade</th>
              <th className="py-2.5 pr-3 text-right font-medium">Valor</th>
              <th className="py-2.5 pr-3 font-medium">Corretora</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <RowLines key={r.id} row={r} decision={decisions[r.id]} onDecision={onDecision} />
            ))}
          </tbody>
        </table>
      </div>
      {/* Celular: cards */}
      <ul className="space-y-2.5 md:hidden">
        {shown.map((r) => (
          <li key={r.id} className="glass-inset space-y-2 p-3.5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate font-medium">{assetOf(r)}</div>
                <div className="text-[12px] text-muted">
                  Linha {r.line_numbers[0]}
                  {r.draft ? <> · <span data-num>{formatDate(r.draft.trade_date)}</span></> : null}
                </div>
              </div>
              <StatusBadge status={r.status} />
            </div>
            {r.draft ? (
              <div className="flex items-end justify-between gap-3 text-[13px]">
                <span className="text-muted">{kindOf(r)}{r.draft.quantity ? <> · <span data-num>{formatQuantity(Number(r.draft.quantity))}</span></> : null}</span>
                <span data-num className="shrink-0 font-semibold">{valueOf(r)}</span>
              </div>
            ) : null}
            {r.draft && originalText(r.draft) ? <div data-num className="text-right text-[12px] text-muted">{originalText(r.draft)}</div> : null}
            <Messages row={r} />
            {r.status === "possible_duplicate" ? <DecisionSelect row={r} value={decisions[r.id]} onChange={onDecision} /> : null}
          </li>
        ))}
      </ul>
      {visible.length > limit ? (
        <div className="flex justify-center pt-3">
          <GlassButton onClick={() => setLimit((n) => n + PAGE)}>Mostrar mais ({shown.length} de {visible.length})</GlassButton>
        </div>
      ) : null}
    </GlassCard>
  );
}

function RowLines({ row, decision, onDecision }: { row: ImportRow; decision?: ImportDecision; onDecision: (rowId: string, d: ImportDecision) => void }) {
  const d = row.draft;
  const hasDetail = row.messages.length > 0 || row.status === "possible_duplicate";
  return (
    <>
      <tr className={`align-middle ${hasDetail ? "" : "border-b border-white/[0.06]"}`}>
        <td data-num className="py-2.5 pr-3 text-muted">{row.line_numbers.join(", ")}</td>
        <td className="py-2.5 pr-3"><StatusBadge status={row.status} /></td>
        <td data-num className="py-2.5 pr-3 whitespace-nowrap text-muted">{d ? formatDate(d.trade_date) : row.raw.data ?? ""}</td>
        <td className="py-2.5 pr-3 whitespace-nowrap">{kindOf(row)}</td>
        <td className="max-w-[220px] truncate py-2.5 pr-3 font-medium">{assetOf(row)}</td>
        <td data-num className="py-2.5 pr-3 text-right">{d?.quantity ? formatQuantity(Number(d.quantity)) : ""}</td>
        <td data-num className="py-2.5 pr-3 text-right font-medium">
          {valueOf(row)}
          {d && originalText(d) ? <div className="text-[11px] font-normal text-muted">{originalText(d)}</div> : null}
        </td>
        <td className="py-2.5 pr-3 whitespace-nowrap text-muted">{d?.broker_name ?? row.raw.corretora ?? row.raw.instituicao ?? ""}</td>
      </tr>
      {hasDetail ? (
        <tr className="border-b border-white/[0.06]">
          <td />
          <td colSpan={7} className="pb-3">
            <div className="flex flex-wrap items-center gap-3">
              <Messages row={row} />
              {row.status === "possible_duplicate" ? <DecisionSelect row={row} value={decision} onChange={onDecision} /> : null}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function StatusBadge({ status }: { status: ImportRowStatus }) {
  return <span className={`inline-flex shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap ${STATUS_STYLE[status]}`}>{STATUS_LABEL[status]}</span>;
}

function Messages({ row }: { row: ImportRow }) {
  if (!row.messages.length) return null;
  return (
    <ul className="space-y-0.5 text-[12px]">
      {row.messages.map((m) => (
        <li key={m.text} className={m.level === "error" ? "text-loss" : m.level === "warning" ? "text-gold" : "text-muted"}>
          {m.text}
        </li>
      ))}
    </ul>
  );
}

function DecisionSelect({ row, value, onChange }: { row: ImportRow; value?: ImportDecision; onChange: (rowId: string, d: ImportDecision) => void }) {
  return (
    <SelectInput
      aria-label={`O que fazer com a linha ${row.line_numbers[0]}`}
      value={value ?? "keep_existing"}
      onChange={(e) => onChange(row.id, e.target.value as ImportDecision)}
      className="h-9 w-full text-[13px] sm:w-[230px]"
    >
      {(Object.keys(DECISION_LABEL) as (keyof typeof DECISION_LABEL)[]).map((k) => (
        <option key={k} value={k}>{DECISION_LABEL[k]}</option>
      ))}
    </SelectInput>
  );
}

function assetOf(r: ImportRow): string {
  return r.draft?.asset_label || r.raw.produto || r.raw.ativo || r.raw.codigo || r.raw.moeda || "";
}

function kindOf(r: ImportRow): string {
  const d = r.draft;
  if (!d) return r.raw.movimentacao ?? r.raw.tipo ?? "";
  if (d.opening_balance) return "Saldo inicial";
  if (d.type === "provento" && d.income_kind) return INCOME_LABEL[d.income_kind] ?? TYPE_LABEL.provento;
  return TYPE_LABEL[d.type];
}

function valueOf(r: ImportRow): string {
  const d = r.draft;
  if (!d) return "";
  if (d.amount) return formatBRL(Number(d.amount));
  if (d.quantity && d.unit_price) return formatBRL(Number(d.quantity) * Number(d.unit_price));
  if (d.factor) return `fator ${formatQuantity(Number(d.factor))}`;
  return "";
}

function ActionBar({ count, busy, disabled, hint, onImport, onDiscard }: {
  count: number;
  busy?: boolean;
  disabled?: boolean;
  hint?: string;
  onImport?: () => void;
  onDiscard?: () => void;
}) {
  return (
    // Barra fixa mais opaca que o vidro comum: as linhas que passam por trás não competem com ela.
    <div
      className="glass-card sticky bottom-24 z-10 flex flex-col gap-3 p-4 sm:bottom-6 sm:flex-row sm:items-center sm:justify-between"
      style={{ background: "rgba(12, 12, 14, 0.78)" }}
    >
      <p className="text-[14px]">
        <span className="font-semibold">{count === 1 ? "1 movimentação" : `${count} movimentações`}</span>
        <span className="text-muted"> {count === 1 ? "vai entrar" : "vão entrar"} no ledger.</span>
        <span className="hidden text-muted sm:inline"> Nada é gravado antes de você confirmar.</span>
      </p>
      <div className="flex gap-2">
        <GlassButton onClick={onDiscard} disabled={disabled || busy} title={hint} className="disabled:cursor-not-allowed disabled:opacity-60">
          Descartar
        </GlassButton>
        <PrimaryButton onClick={onImport} disabled={disabled || busy || count === 0} title={hint} className="disabled:cursor-not-allowed disabled:opacity-60">
          {busy ? "Gravando..." : `Importar ${count}`}
        </PrimaryButton>
      </div>
    </div>
  );
}
