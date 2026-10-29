/**
 * Escrita no ledger pelo /app. Fluxo de confirmação: "Conferir" mostra o que vai acontecer
 * (erros, duplicados prováveis); só "Confirmar" grava. A chave de idempotência nasce com
 * o formulário: clique duplo não duplica nada.
 */
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useAppSource, useBrokers, useRefreshAfterWrite, todaySP } from "@/data/context";
import { ApiError, type CheckIssue, type DraftCheck, type ManualEntry, type MovementPatch } from "@/data/api";
import type { Asset, MovementRow, MovementType } from "@/data/types";
import { formatDate } from "@/lib/format";
import { INCOME_LABEL, TYPE_LABEL } from "@/lib/movements";
import { tokens } from "@/theme/tokens";
import { GlassButton, PrimaryButton } from "@/ui/controls";
import { Dialog } from "@/ui/Dialog";
import { Field, SelectInput, TextArea, TextInput } from "@/ui/forms";

const TRADE: MovementType[] = ["compra", "venda"];
const FIXED: MovementType[] = ["aporte", "resgate"];
const EVENTS: MovementType[] = ["desdobramento", "grupamento", "bonificacao"];

function Issues({ issues }: { issues: CheckIssue[] }) {
  if (!issues.length) return null;
  return (
    <ul role="alert" className="space-y-1.5 rounded-[14px] border border-loss/40 bg-loss/10 p-3 text-[13px] text-ink">
      {issues.map((i) => (
        <li key={`${i.code}-${i.field}-${i.message}`} className="flex gap-2">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-loss" />
          <span>{i.message}</span>
        </li>
      ))}
    </ul>
  );
}

function CheckSummary({ check }: { check: DraftCheck }) {
  if (!check.ok) return <Issues issues={check.errors} />;
  return (
    <div className="space-y-2 rounded-[14px] border border-gain/35 bg-gain/10 p-3 text-[13px]">
      <div className="flex items-center gap-2 font-medium">
        <CheckCircle2 className="size-4 text-gain" />
        {check.already_posted ? "Esta movimentação já foi gravada." : "Tudo certo para gravar."}
      </div>
      {check.duplicates.length ? (
        <div className="flex gap-2 text-muted">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" style={{ color: tokens.color.gold }} />
          <span>
            Parece a mesma operação já registrada por outra origem (
            {check.duplicates.map((d) => `${d.origin_label ?? d.origin} em ${formatDate(d.trade_date)}`).join("; ")}). Se for
            outra operação, pode confirmar.
          </span>
        </div>
      ) : null}
    </div>
  );
}

/** Busca de ticker com sugestões (marts.assets). */
function AssetPicker({ value, onChange }: { value: string; onChange: (ticker: string) => void }) {
  const source = useAppSource();
  const [term, setTerm] = useState(value);
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ["app", "asset-search", term],
    queryFn: () => (source ? source.searchAssets(term) : Promise.resolve([] as Asset[])),
    enabled: Boolean(source) && term.trim().length >= 2 && open,
    staleTime: 60_000,
  });
  return (
    <div className="relative">
      <TextInput
        id="mov-ativo"
        value={term}
        autoComplete="off"
        placeholder="PETR4, HGLG11, BTC..."
        onChange={(e) => {
          setTerm(e.target.value.toUpperCase());
          onChange(e.target.value.toUpperCase());
          setOpen(true);
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onFocus={() => setOpen(true)}
      />
      {open && query.data?.length ? (
        <ul className="absolute inset-x-0 top-12 z-10 max-h-60 overflow-y-auto rounded-[14px] border border-white/15 bg-[rgba(28,22,18,0.96)] p-1 shadow-lifted">
          {query.data.map((a) => (
            <li key={a.id}>
              <button
                type="button"
                className="flex w-full items-center justify-between gap-3 rounded-[10px] px-3 py-2 text-left text-[13px] hover:bg-white/10"
                onMouseDown={() => {
                  setTerm(a.ticker);
                  onChange(a.ticker);
                  setOpen(false);
                }}
              >
                <span className="font-semibold">{a.ticker}</span>
                <span className="truncate text-muted">{a.name}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

type FormState = {
  type: MovementType;
  trade_date: string;
  broker_id: string;
  ticker: string;
  quantity: string;
  unit_price: string;
  fees: string;
  amount: string;
  factor: string;
  income_kind: NonNullable<ManualEntry["income_kind"]>;
  instrument_id: string; // "" = novo título
  fi_kind: NonNullable<ManualEntry["fi_kind"]>;
  fi_issuer: string;
  fi_rate_pct: string;
  fi_maturity: string;
  notes: string;
  opening: boolean; // saldo inicial: compra marcada, com o custo médio
};

function emptyForm(): FormState {
  return {
    type: "compra", trade_date: todaySP(), broker_id: "", ticker: "", quantity: "", unit_price: "", fees: "",
    amount: "", factor: "", income_kind: "dividendo", instrument_id: "", fi_kind: "CDB", fi_issuer: "",
    fi_rate_pct: "", fi_maturity: "", notes: "", opening: false,
  };
}

function toEntry(f: FormState, clientKey: string): ManualEntry {
  const base: ManualEntry = { client_key: clientKey, type: f.type, trade_date: f.trade_date, broker_id: f.broker_id };
  const opt = (v: string) => (v.trim() ? v.trim() : undefined);
  if (TRADE.includes(f.type)) Object.assign(base, { ticker: opt(f.ticker), quantity: opt(f.quantity), unit_price: opt(f.unit_price), fees: f.opening ? undefined : opt(f.fees) });
  if (f.opening) base.opening_balance = true;
  if (f.type === "provento") Object.assign(base, { ticker: opt(f.ticker), amount: opt(f.amount), income_kind: f.income_kind });
  if (EVENTS.includes(f.type)) Object.assign(base, { ticker: opt(f.ticker), factor: opt(f.factor), unit_price: f.type === "bonificacao" ? opt(f.unit_price) ?? "0" : undefined });
  if (FIXED.includes(f.type)) {
    Object.assign(base, { amount: opt(f.amount) });
    if (f.instrument_id) Object.assign(base, { instrument_id: f.instrument_id });
    else Object.assign(base, { fi_kind: f.fi_kind, fi_issuer: opt(f.fi_issuer), fi_rate_pct: opt(f.fi_rate_pct), fi_maturity: opt(f.fi_maturity) });
  }
  if (f.notes.trim()) base.notes = f.notes.trim();
  return base;
}

export function ManualEntryDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const source = useAppSource();
  const brokers = useBrokers();
  const refresh = useRefreshAfterWrite();
  const instruments = useQuery({ queryKey: ["app", "fi"], queryFn: () => source!.fiInstruments(), enabled: Boolean(source) && open });
  const [form, setForm] = useState<FormState>(emptyForm);
  const [clientKey, setClientKey] = useState(() => crypto.randomUUID());
  const [check, setCheck] = useState<DraftCheck | null>(null);
  const [issues, setIssues] = useState<CheckIssue[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(emptyForm());
      setClientKey(crypto.randomUUID());
      setCheck(null);
      setIssues([]);
    }
  }, [open]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setCheck(null);
  };
  const chosenInstrument = useMemo(() => instruments.data?.find((i) => i.id === form.instrument_id), [instruments.data, form.instrument_id]);
  useEffect(() => {
    if (chosenInstrument) setForm((f) => ({ ...f, broker_id: chosenInstrument.broker_id }));
  }, [chosenInstrument]);

  if (!source) return null;
  const entry = toEntry(form, clientKey);

  async function run(action: "check" | "post") {
    if (!source) return;
    setBusy(true);
    setIssues([]);
    try {
      if (action === "check") {
        const result = await source.api.checkManual([entry]);
        setCheck(result.checks[0] ?? null);
      } else {
        await source.api.postManual([entry]);
        await refresh();
        onClose();
      }
    } catch (e) {
      if (e instanceof ApiError) {
        const first = e.body.checks?.[0];
        if (first) setCheck(first);
        else setIssues([{ code: "erro", message: e.message, field: e.body.field ?? null }]);
      } else setIssues([{ code: "erro", message: "Sem conexão com a API. Tente de novo.", field: null }]);
    } finally {
      setBusy(false);
    }
  }

  const t = form.type;
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Novo lançamento"
      wide
      footer={
        <>
          <GlassButton onClick={onClose}>Cancelar</GlassButton>
          {check?.ok ? (
            <PrimaryButton onClick={() => run("post")} disabled={busy || Boolean(check.already_posted)}>
              Confirmar lançamento
            </PrimaryButton>
          ) : (
            <PrimaryButton onClick={() => run("check")} disabled={busy}>
              Conferir
            </PrimaryButton>
          )}
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Tipo" htmlFor="mov-tipo">
          <SelectInput
            id="mov-tipo"
            value={form.opening ? "saldo_inicial" : t}
            onChange={(e) => {
              // "Saldo inicial" é uma compra marcada: posição anterior ao histórico.
              const opening = e.target.value === "saldo_inicial";
              set("opening", opening);
              set("type", opening ? "compra" : (e.target.value as MovementType));
            }}
          >
            {(Object.keys(TYPE_LABEL) as MovementType[]).map((k) => (
              <option key={k} value={k}>{TYPE_LABEL[k]}</option>
            ))}
            <option value="saldo_inicial">Saldo inicial</option>
          </SelectInput>
        </Field>
        <Field label="Data" htmlFor="mov-data">
          <TextInput id="mov-data" type="date" value={form.trade_date} onChange={(e) => set("trade_date", e.target.value)} />
        </Field>

        {!FIXED.includes(t) ? (
          <Field label="Ativo" htmlFor="mov-ativo" hint="Ticker da B3, título do Tesouro ou cripto">
            <AssetPicker value={form.ticker} onChange={(v) => set("ticker", v)} />
          </Field>
        ) : (
          <Field label="Título de renda fixa" htmlFor="mov-titulo">
            <SelectInput id="mov-titulo" value={form.instrument_id} onChange={(e) => set("instrument_id", e.target.value)}>
              <option value="">Novo título</option>
              {instruments.data?.map((i) => (
                <option key={i.id} value={i.id}>{i.label}</option>
              ))}
            </SelectInput>
          </Field>
        )}
        <Field label="Corretora" htmlFor="mov-corretora">
          <SelectInput id="mov-corretora" value={form.broker_id} disabled={Boolean(chosenInstrument)} onChange={(e) => set("broker_id", e.target.value)}>
            <option value="">Escolha</option>
            {brokers.data?.map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </SelectInput>
        </Field>

        {FIXED.includes(t) && !form.instrument_id ? (
          <>
            <Field label="Tipo do título" htmlFor="mov-fi-kind">
              <SelectInput id="mov-fi-kind" value={form.fi_kind} onChange={(e) => set("fi_kind", e.target.value as FormState["fi_kind"])}>
                <option value="CDB">CDB</option>
                <option value="LCI">LCI</option>
                <option value="LCA">LCA</option>
              </SelectInput>
            </Field>
            <Field label="Emissor" htmlFor="mov-fi-emissor">
              <TextInput id="mov-fi-emissor" value={form.fi_issuer} onChange={(e) => set("fi_issuer", e.target.value)} placeholder="Banco" />
            </Field>
            <Field label="% do CDI" htmlFor="mov-fi-taxa">
              <TextInput id="mov-fi-taxa" inputMode="decimal" value={form.fi_rate_pct} onChange={(e) => set("fi_rate_pct", e.target.value)} placeholder="110" />
            </Field>
            <Field label="Vencimento" htmlFor="mov-fi-venc">
              <TextInput id="mov-fi-venc" type="date" value={form.fi_maturity} onChange={(e) => set("fi_maturity", e.target.value)} />
            </Field>
          </>
        ) : null}

        {TRADE.includes(t) ? (
          <>
            <Field label="Quantidade" htmlFor="mov-qtd">
              <TextInput id="mov-qtd" inputMode="decimal" value={form.quantity} onChange={(e) => set("quantity", e.target.value)} placeholder="100" />
            </Field>
            <Field
              label={form.opening ? "Custo médio (R$)" : "Preço unitário (R$)"}
              htmlFor="mov-preco"
              hint={form.opening ? "Posição que você já tinha antes do histórico" : undefined}
            >
              <TextInput id="mov-preco" inputMode="decimal" value={form.unit_price} onChange={(e) => set("unit_price", e.target.value)} placeholder="38,45" />
            </Field>
            {form.opening ? null : (
              <Field label="Taxas (R$)" htmlFor="mov-taxas" hint="Corretagem e emolumentos; entram no preço médio">
                <TextInput id="mov-taxas" inputMode="decimal" value={form.fees} onChange={(e) => set("fees", e.target.value)} placeholder="0,00" />
              </Field>
            )}
          </>
        ) : null}

        {t === "provento" ? (
          <Field label="Tipo de provento" htmlFor="mov-provento">
            <SelectInput id="mov-provento" value={form.income_kind} onChange={(e) => set("income_kind", e.target.value as FormState["income_kind"])}>
              {Object.entries(INCOME_LABEL).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </SelectInput>
          </Field>
        ) : null}
        {t === "provento" || FIXED.includes(t) ? (
          <Field label="Valor (R$)" htmlFor="mov-valor" hint={FIXED.includes(t) ? "Valor bruto" : undefined}>
            <TextInput id="mov-valor" inputMode="decimal" value={form.amount} onChange={(e) => set("amount", e.target.value)} placeholder="1.000,00" />
          </Field>
        ) : null}

        {EVENTS.includes(t) ? (
          <>
            <Field
              label="Fator"
              htmlFor="mov-fator"
              hint={t === "bonificacao" ? "Ações novas por ação possuída (0,1 = 10%)" : t === "desdobramento" ? "Cada ação vira quantas (ex.: 2)" : "Ex.: 0,1 = 10 viram 1"}
            >
              <TextInput id="mov-fator" inputMode="decimal" value={form.factor} onChange={(e) => set("factor", e.target.value)} />
            </Field>
            {t === "bonificacao" ? (
              <Field label="Custo atribuído por ação (R$)" htmlFor="mov-custo" hint="Informado pela empresa; pode ser zero">
                <TextInput id="mov-custo" inputMode="decimal" value={form.unit_price} onChange={(e) => set("unit_price", e.target.value)} placeholder="0,00" />
              </Field>
            ) : null}
          </>
        ) : null}

        <div className="sm:col-span-2">
          <Field label="Observação" htmlFor="mov-obs">
            <TextArea id="mov-obs" value={form.notes} onChange={(e) => set("notes", e.target.value)} rows={2} />
          </Field>
        </div>
        <div className="space-y-3 sm:col-span-2">
          <Issues issues={issues} />
          {check ? <CheckSummary check={check} /> : null}
        </div>
      </div>
    </Dialog>
  );
}

const EDIT_FIELDS: Record<MovementType, (keyof MovementPatch)[]> = {
  compra: ["trade_date", "quantity", "unit_price", "fees"],
  venda: ["trade_date", "quantity", "unit_price", "fees"],
  aporte: ["trade_date", "amount"],
  resgate: ["trade_date", "amount"],
  provento: ["trade_date", "amount"],
  desdobramento: ["trade_date", "factor"],
  grupamento: ["trade_date", "factor"],
  bonificacao: ["trade_date", "factor", "unit_price"],
};

const FIELD_LABEL: Partial<Record<keyof MovementPatch, string>> = {
  trade_date: "Data",
  quantity: "Quantidade",
  unit_price: "Preço unitário (R$)",
  fees: "Taxas (R$)",
  amount: "Valor (R$)",
  factor: "Fator",
};

const asText = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v).replace(".", ","));

export function EditMovementDialog({ movement, onClose }: { movement: MovementRow | null; onClose: () => void }) {
  const source = useAppSource();
  const refresh = useRefreshAfterWrite();
  const [values, setValues] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [issues, setIssues] = useState<CheckIssue[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!movement) return;
    setValues({
      trade_date: movement.trade_date,
      quantity: asText(movement.quantity),
      unit_price: asText(movement.unit_price),
      fees: asText(movement.fees ?? 0),
      amount: asText(movement.amount),
      factor: asText(movement.factor),
    });
    setReason("");
    setIssues([]);
  }, [movement]);

  if (!source || !movement) return null;
  const fields = EDIT_FIELDS[movement.type];

  async function save() {
    if (!source || !movement) return;
    const original: Record<string, string> = {
      trade_date: movement.trade_date,
      quantity: asText(movement.quantity),
      unit_price: asText(movement.unit_price),
      fees: asText(movement.fees ?? 0),
      amount: asText(movement.amount),
      factor: asText(movement.factor),
    };
    const patch: MovementPatch = {};
    for (const f of fields) {
      const v = values[f] ?? "";
      if (v !== original[f]) (patch as Record<string, string>)[f] = v;
    }
    if (Object.keys(patch).length === 0) return onClose();
    if (reason.trim()) patch.reason = reason.trim();
    setBusy(true);
    try {
      await source.api.editMovement(movement.id, patch);
      await refresh();
      onClose();
    } catch (e) {
      const message = e instanceof ApiError ? (e.body.issues?.[0]?.message ?? e.message) : "Sem conexão com a API.";
      setIssues([{ code: "erro", message, field: null }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={Boolean(movement)}
      onClose={onClose}
      title={`Editar ${TYPE_LABEL[movement.type].toLowerCase()} de ${movement.asset_label}`}
      footer={
        <>
          <GlassButton onClick={onClose}>Cancelar</GlassButton>
          <PrimaryButton onClick={save} disabled={busy}>Salvar alteração</PrimaryButton>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map((f) => (
          <Field key={f} label={FIELD_LABEL[f] ?? f} htmlFor={`edit-${f}`}>
            <TextInput
              id={`edit-${f}`}
              type={f === "trade_date" ? "date" : "text"}
              inputMode={f === "trade_date" ? undefined : "decimal"}
              value={values[f] ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [f]: e.target.value }))}
            />
          </Field>
        ))}
        <div className="sm:col-span-2">
          <Field label="Motivo da edição" htmlFor="edit-motivo" hint="Fica no histórico de auditoria">
            <TextInput id="edit-motivo" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ex.: taxa da nota de corretagem" />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Issues issues={issues} />
        </div>
      </div>
    </Dialog>
  );
}

export function VoidMovementDialog({ movement, onClose }: { movement: MovementRow | null; onClose: () => void }) {
  const source = useAppSource();
  const refresh = useRefreshAfterWrite();
  const [reason, setReason] = useState("");
  const [issues, setIssues] = useState<CheckIssue[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setReason("");
    setIssues([]);
  }, [movement]);
  if (!source || !movement) return null;

  async function confirm() {
    if (!source || !movement) return;
    setBusy(true);
    try {
      await source.api.voidMovement(movement.id, reason.trim());
      await refresh();
      onClose();
    } catch (e) {
      const message = e instanceof ApiError ? (e.body.issues?.[0]?.message ?? e.message) : "Sem conexão com a API.";
      setIssues([{ code: "erro", message, field: null }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={Boolean(movement)}
      onClose={onClose}
      title="Remover movimentação"
      footer={
        <>
          <GlassButton onClick={onClose}>Cancelar</GlassButton>
          <button
            type="button"
            onClick={confirm}
            disabled={busy || !reason.trim()}
            className="inline-flex h-11 items-center rounded-full bg-loss px-5 text-[14px] font-semibold text-on-light disabled:opacity-50"
          >
            Remover
          </button>
        </>
      }
    >
      <div className="space-y-4 text-[14px]">
        <p className="text-muted">
          {TYPE_LABEL[movement.type]} de {movement.asset_label} em {formatDate(movement.trade_date)}. A movimentação sai da
          carteira, mas continua no histórico de auditoria (nada é apagado de vez).
        </p>
        <Field label="Motivo (obrigatório)" htmlFor="void-motivo">
          <TextInput id="void-motivo" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ex.: lançada em duplicidade" />
        </Field>
        <Issues issues={issues} />
      </div>
    </Dialog>
  );
}
