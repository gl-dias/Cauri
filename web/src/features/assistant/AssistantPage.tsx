import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, MessageSquarePlus, Mic, MicOff, Pencil, Send, Trash2 } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, type ChatMessage, type Proposal, type ProposalItem } from "@/data/api";
import { useAppSource, useBrokers, usePositions, useRefreshAfterWrite } from "@/data/context";
import type { AppSource } from "@/data/source";
import { formatBRL, formatDate, formatQuantity } from "@/lib/format";
import { INCOME_LABEL, originalText, TYPE_LABEL } from "@/lib/movements";
import { tokens, type AssetClassKey } from "@/theme/tokens";
import { GlassButton, PrimaryButton } from "@/ui/controls";
import { Field, SelectInput, TextArea, TextInput } from "@/ui/forms";
import { CardHeader, GlassCard } from "@/ui/GlassCard";
import { pageVariants, staticVariants } from "@/ui/motion";
import { OpeningSuggestionCard } from "@/features/shared/OpeningSuggestionCard";

import { SAMPLE_CONVERSATION, SAMPLE_CONVERSATIONS } from "./sample";
import { useVoice } from "./voice";

const STATUS: Record<ProposalItem["status"], { label: string; style: string }> = {
  ok: { label: "pronta", style: "text-gain [background:color-mix(in_srgb,var(--cauri-gain)_16%,rgba(0,0,0,0.74))]" },
  duplicado: { label: "possível duplicada", style: "text-gold [background:color-mix(in_srgb,var(--cauri-gold)_14%,rgba(0,0,0,0.74))]" },
  erro: { label: "com erro", style: "text-loss [background:color-mix(in_srgb,var(--cauri-loss)_16%,rgba(0,0,0,0.74))]" },
  pergunta: { label: "pergunta", style: "text-gold [background:color-mix(in_srgb,var(--cauri-gold)_14%,rgba(0,0,0,0.74))]" },
  gravado: { label: "gravada", style: "bg-black/45 text-muted" },
};
const EXAMPLES = ["comprei 3 petrobras e vendi 2 itau", "comprei 0,01 bitcoin a 120 mil dólares", "recebi 48 reais de taesa ontem"];

export function AssistantPage() {
  const reduced = useReducedMotion();
  const app = useAppSource();
  return (
    <motion.div variants={reduced ? staticVariants : pageVariants} initial="hidden" animate="show" className="space-y-5 sm:space-y-6">
      <header>
        <h1 className="text-[28px] font-semibold tracking-tight sm:text-[34px]">Assistente</h1>
        <p className="mt-1 text-[14px] text-muted">
          Fale ou escreva a operação. O Cauri mostra um cartão para você conferir antes de gravar{app ? "" : " · vitrine no demo"}
        </p>
      </header>
      {app ? <Chat app={app} /> : <Showcase />}
    </motion.div>
  );
}

/* /demo: conversa gravada, sem nenhuma chamada ao backend ------------------------------ */

function Showcase() {
  return (
    <Layout
      conversations={SAMPLE_CONVERSATIONS}
      activeId={SAMPLE_CONVERSATION.id}
      onPick={() => {}}
      onNew={() => {}}
      chat={
        <ChatCard
          messages={SAMPLE_CONVERSATION.messages}
          composer={<Composer disabled hint="Somente leitura no demo" onSend={() => {}} />}
          renderProposal={(p) => <ProposalCard proposal={p} readOnly />}
        />
      }
    />
  );
}

/* /app ------------------------------------------------------------------------------- */

function Chat({ app }: { app: AppSource }) {
  const client = useQueryClient();
  const refresh = useRefreshAfterWrite();
  const config = useQuery({ queryKey: ["app", "assistant-config"], queryFn: () => app.api.assistant.config(), staleTime: Infinity });
  const conversations = useQuery({ queryKey: ["app", "conversations"], queryFn: () => app.api.assistant.conversations() });
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const load = useMutation({
    mutationFn: (id: string) => app.api.assistant.conversation(id),
    onSuccess: (conv) => {
      setActiveId(conv.id);
      setMessages(conv.messages);
    },
  });
  const send = useMutation({
    mutationFn: ({ text, mode }: { text: string; mode: "texto" | "voz" }) => app.api.assistant.send(text, activeId, mode),
    onSuccess: async (result) => {
      setActiveId(result.conversation_id);
      setMessages((m) => [...m, ...result.messages]);
      await client.invalidateQueries({ queryKey: ["app", "conversations"] });
    },
  });

  const replaceProposal = useCallback((updated: Proposal) => {
    setMessages((list) => list.map((m) => (m.proposal?.id === updated.id ? { ...m, proposal: updated } : m)));
  }, []);
  const afterConfirm = useCallback(async () => {
    if (activeId) load.mutate(activeId);
    await refresh();
  }, [activeId, load, refresh]);

  const unavailable = config.data?.llm === "indisponivel";
  return (
    <Layout
      conversations={conversations.data ?? []}
      activeId={activeId}
      onPick={(id) => load.mutate(id)}
      onNew={() => {
        setActiveId(null);
        setMessages([]);
      }}
      chat={
        <ChatCard
          messages={messages}
          empty={
            <div className="space-y-3 py-6 text-center">
              <p className="text-[14px] text-muted">Experimente:</p>
              <div className="flex flex-wrap justify-center gap-2">
                {EXAMPLES.map((e) => (
                  <button key={e} type="button" onClick={() => send.mutate({ text: e, mode: "texto" })} className="glass-pill px-3 py-1.5 text-[13px] text-ink hover:bg-white/15">
                    {e}
                  </button>
                ))}
              </div>
            </div>
          }
          composer={
            <Composer
              disabled={unavailable || send.isPending}
              busy={send.isPending}
              hint={unavailable ? "Assistente sem chave da Anthropic no servidor" : undefined}
              onSend={(text, mode) => send.mutate({ text, mode })}
              voiceMode={config.data?.voice}
              transcribe={(audio) => app.api.assistant.transcribe(audio).then((r) => r.text)}
              error={send.error instanceof ApiError ? send.error.message : send.error ? "Sem conexão com a API." : null}
              note={config.data?.llm === "regras" ? "Modo de desenvolvimento: frases simples, sem IA." : undefined}
            />
          }
          renderProposal={(p) => <ProposalCard proposal={p} app={app} onChange={replaceProposal} onConfirmed={afterConfirm} />}
        />
      }
    />
  );
}

/* Estrutura em três colunas ------------------------------------------------------------- */

function Layout({ conversations, activeId, onPick, onNew, chat }: {
  conversations: { id: string; title: string; updated_at: string }[];
  activeId: string | null;
  onPick: (id: string) => void;
  onNew: () => void;
  chat: React.ReactNode;
}) {
  const [showList, setShowList] = useState(false);
  const list = (
    <GlassCard lift={false}>
      <CardHeader
        title="Conversas"
        action={
          <button type="button" aria-label="Nova conversa" onClick={onNew} className="grid size-9 place-items-center rounded-full text-muted hover:bg-white/10 hover:text-ink">
            <MessageSquarePlus className="size-4" />
          </button>
        }
      />
      {conversations.length ? (
        <ul className="space-y-1.5">
          {conversations.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => onPick(c.id)}
                className={`w-full rounded-[14px] px-3 py-2.5 text-left text-[13px] transition-colors ${c.id === activeId ? "bg-white/15 text-ink" : "text-muted hover:bg-white/10 hover:text-ink"}`}
              >
                <div className="truncate font-medium">{c.title}</div>
                <div data-num className="text-[12px] text-muted">{formatDate(c.updated_at.slice(0, 10))}</div>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted">Nenhuma conversa ainda.</p>
      )}
    </GlassCard>
  );
  return (
    <div className="grid grid-cols-1 gap-5 sm:gap-6 lg:grid-cols-12">
      <aside className="hidden min-w-0 lg:col-span-3 lg:block">{list}</aside>
      <section className="min-w-0 space-y-4 lg:col-span-6">
        <div className="flex gap-2 lg:hidden">
          <GlassButton onClick={() => setShowList((v) => !v)} aria-expanded={showList}>Conversas</GlassButton>
          <GlassButton onClick={onNew}><MessageSquarePlus className="size-4" /> Nova</GlassButton>
        </div>
        {showList ? <div className="lg:hidden">{list}</div> : null}
        {chat}
      </section>
      <aside className="hidden min-w-0 lg:col-span-3 lg:block">
        <PortfolioSummary />
      </aside>
    </div>
  );
}

function PortfolioSummary() {
  const positions = usePositions();
  const rows = useMemo(() => [...(positions.data ?? [])].sort((a, b) => b.market_value - a.market_value), [positions.data]);
  const total = rows.reduce((sum, p) => sum + p.market_value, 0);
  return (
    <GlassCard lift={false}>
      <CardHeader title="Sua carteira" subtitle="Para conferir enquanto conversa. O assistente nunca envia isto para a IA." />
      <div data-num className="mb-4 text-[24px] font-semibold">{formatBRL(total)}</div>
      <ul className="space-y-2">
        {rows.slice(0, 7).map((p) => (
          <li key={`${p.label}-${p.broker_id}`} className="flex items-center justify-between gap-3 text-[13px]">
            <span className="flex min-w-0 items-center gap-2">
              <span className="size-2 shrink-0 rounded-full" style={{ background: tokens.assetClass[p.asset_class as AssetClassKey]?.color }} />
              <span className="truncate font-medium">{p.label}</span>
            </span>
            <span data-num className="shrink-0 text-muted">{formatBRL(p.market_value)}</span>
          </li>
        ))}
      </ul>
    </GlassCard>
  );
}

/* Conversa ---------------------------------------------------------------------------- */

function ChatCard({ messages, composer, renderProposal, empty }: {
  messages: ChatMessage[];
  composer: React.ReactNode;
  renderProposal: (p: Proposal) => React.ReactNode;
  empty?: React.ReactNode;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [messages.length]);
  return (
    <GlassCard lift={false} className="space-y-4">
      {messages.length === 0 ? empty : null}
      <ol className="space-y-4">
        {messages.map((m) => (
          <li key={m.id} className={m.role === "user" ? "flex justify-end" : "space-y-3"}>
            {m.role === "user" ? (
              <div className="max-w-[85%] rounded-[18px] rounded-br-[6px] border border-primary/50 px-4 py-2.5 text-[14px] [background:color-mix(in_srgb,var(--cauri-primary)_42%,rgba(0,0,0,0.6))]">
                {m.content}
                {m.input_mode === "voz" ? <span className="ml-2 text-[11px] text-muted">(voz)</span> : null}
              </div>
            ) : (
              <>
                <div className="glass-inset max-w-[85%] px-4 py-2.5 text-[14px]">{m.content}</div>
                {m.proposal ? renderProposal(m.proposal) : null}
              </>
            )}
          </li>
        ))}
      </ol>
      <div ref={end} />
      {composer}
    </GlassCard>
  );
}

function Composer({ onSend, disabled, busy, hint, voiceMode, transcribe, error, note }: {
  onSend: (text: string, mode: "texto" | "voz") => void;
  disabled?: boolean;
  busy?: boolean;
  hint?: string;
  voiceMode?: "groq" | "navegador";
  transcribe?: (audio: Blob) => Promise<string>;
  error?: string | null;
  note?: string;
}) {
  const [text, setText] = useState("");
  const [fromVoice, setFromVoice] = useState(false);
  const voice = useVoice(
    voiceMode,
    transcribe ?? (() => Promise.reject(new Error("sem transcrição"))),
    useCallback((t: string) => {
      setText(t);
      setFromVoice(true);
    }, []),
  );
  const submit = () => {
    const value = text.trim();
    if (!value || disabled) return;
    onSend(value, fromVoice ? "voz" : "texto");
    setText("");
    setFromVoice(false);
  };
  return (
    <div className="space-y-2 border-t border-white/10 pt-4">
      <div className="flex items-end gap-2">
        <TextArea
          aria-label="Mensagem para o assistente"
          rows={2}
          value={text}
          disabled={disabled && !busy}
          placeholder={hint ?? "Ex.: comprei 10 PETR4 a 38,50 ontem"}
          onChange={(e) => {
            setText(e.target.value);
            setFromVoice(false);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          className="min-h-[52px] flex-1 resize-none"
        />
        <button
          type="button"
          aria-label={voice.listening ? "Parar de gravar" : "Falar"}
          title={voice.supported ? undefined : "Voz indisponível neste navegador"}
          disabled={disabled || !voice.supported || voice.busy}
          onClick={() => (voice.listening ? voice.stop() : void voice.start())}
          className={`glass-pill grid size-12 shrink-0 place-items-center text-ink disabled:cursor-not-allowed disabled:opacity-60 ${voice.listening ? "bg-loss/40" : "hover:bg-white/15"}`}
        >
          {voice.listening ? <MicOff className="size-5" /> : <Mic className="size-5" />}
        </button>
        <PrimaryButton aria-label="Enviar" disabled={disabled || !text.trim()} onClick={submit} className="h-12 shrink-0 px-4 disabled:cursor-not-allowed disabled:opacity-60">
          <Send className="size-4" />
        </PrimaryButton>
      </div>
      {busy ? <p className="text-[13px] text-muted">Entendendo a frase...</p> : null}
      {voice.busy ? <p className="text-[13px] text-muted">Transcrevendo o áudio...</p> : null}
      {voice.error ? <p className="text-[13px] text-loss">{voice.error}</p> : null}
      {error ? <p role="alert" className="text-[13px] text-loss">{error}</p> : null}
      {note ? <p className="text-[12px] text-muted">{note}</p> : null}
    </div>
  );
}

/* Cartão de confirmação ------------------------------------------------------------------ */

function ProposalCard({ proposal, app, onChange, onConfirmed, readOnly = false }: {
  proposal: Proposal;
  app?: AppSource;
  onChange?: (p: Proposal) => void;
  onConfirmed?: () => void;
  readOnly?: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: (fn: () => Promise<Proposal>) => fn(),
    onSuccess: (p) => {
      setError(null);
      onChange?.(p);
      if (p.status === "confirmed") onConfirmed?.();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Sem conexão com a API."),
  });
  const pending = proposal.status === "pending";
  const blocked = proposal.items.some((i) => i.status === "erro" || i.status === "pergunta");
  const api = app?.api.assistant;
  return (
    <div className="glass-inset space-y-3 p-4">
      <div className="flex items-center justify-between gap-2 text-[13px]">
        <span className="font-semibold">
          {proposal.status === "confirmed" ? "Gravado" : proposal.status === "cancelled" ? "Cancelado" : "Confira antes de gravar"}
        </span>
        {proposal.status === "confirmed" ? <CheckCircle2 className="size-4 text-gain" /> : null}
      </div>
      <ul className="space-y-2.5">
        {proposal.items.map((item) => (
          <ItemRow
            key={item.id}
            item={item}
            editable={pending && !readOnly && item.kind !== "contrapartida"}
            onAnswer={(value) => api && item.question && run.mutate(() => api.answer(proposal.id, item.id, item.question!.field, value))}
            onEdit={(changes) => api && run.mutate(() => api.edit(proposal.id, item.id, changes))}
            onRemove={() => api && run.mutate(() => api.remove(proposal.id, item.id))}
            readOnly={readOnly}
          />
        ))}
      </ul>
      {pending
        ? proposal.suggestions.map((s) => (
            <OpeningSuggestionCard
              key={`${s.ticker}-${s.first_shortfall}`}
              compact
              suggestion={s}
              note={readOnly ? "Vitrine: no app, o saldo inicial entra no mesmo cartão." : "O saldo inicial entra junto com o cartão, quando você confirmar."}
              onSubmit={async (body) => {
                if (!api) return;
                onChange?.(await api.addOpening(proposal.id, body));
              }}
            />
          ))
        : null}
      {error ? <p role="alert" className="text-[13px] text-loss">{error}</p> : null}
      {pending ? (
        <div className="flex flex-wrap justify-end gap-2 pt-1">
          <GlassButton disabled={readOnly || run.isPending} onClick={() => api && run.mutate(() => api.cancel(proposal.id))} className="disabled:cursor-not-allowed disabled:opacity-60">
            Cancelar
          </GlassButton>
          <PrimaryButton
            disabled={readOnly || run.isPending || blocked}
            title={readOnly ? "Somente leitura no demo" : blocked ? "Resolva as pendências do cartão" : undefined}
            onClick={() => api && run.mutate(() => api.confirm(proposal.id))}
            className="disabled:cursor-not-allowed disabled:opacity-60"
          >
            {run.isPending ? "Gravando..." : "Confirmar"}
          </PrimaryButton>
        </div>
      ) : null}
    </div>
  );
}

function ItemRow({ item, editable, onAnswer, onEdit, onRemove, readOnly }: {
  item: ProposalItem;
  editable: boolean;
  onAnswer: (value: string) => void;
  onEdit: (changes: { quantidade?: string; preco?: string; data?: string; broker_id?: string }) => void;
  onRemove: () => void;
  readOnly: boolean;
}) {
  const brokers = useBrokers();
  const brokerName = (id?: string) => brokers.data?.find((b) => b.id === id)?.name ?? (id === item.draft?.broker_id ? item.broker_name : undefined) ?? id ?? "";
  const [editing, setEditing] = useState(false);
  const d = item.draft;
  const [quantity, setQuantity] = useState(d?.quantity?.replace(".", ",") ?? "");
  const [price, setPrice] = useState(d?.unit_price?.replace(".", ",") ?? "");
  const [day, setDay] = useState(d?.trade_date ?? "");
  const [broker, setBroker] = useState(d?.broker_id ?? "");
  const value = d?.amount ? Number(d.amount) : d?.quantity && d?.unit_price ? Number(d.quantity) * Number(d.unit_price) : null;
  const kind = item.kind === "contrapartida" ? "Contrapartida" : d?.opening_balance || item.kind === "saldo_inicial" ? "Saldo inicial" : d ? (d.type === "provento" && d.income_kind ? INCOME_LABEL[d.income_kind] : TYPE_LABEL[d.type]) : spokenKind(item.spoken?.tipo);
  return (
    <li className="space-y-2 rounded-[14px] border border-white/10 bg-black/25 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[14px] font-semibold">
            {kind} · {item.ticker ?? item.spoken?.ativo ?? ""}
            {item.asset_name ? <span className="ml-2 text-[12px] font-normal text-muted">{item.asset_name}</span> : null}
          </div>
          {d ? (
            <div className="mt-0.5 text-[13px] text-muted">
              {d.quantity ? <span data-num>{formatQuantity(Number(d.quantity))} × {formatBRL(Number(d.unit_price))}</span> : null}
              {value !== null ? <span data-num className="font-semibold text-ink"> {d.quantity ? "= " : ""}{formatBRL(value)}</span> : null}
              <span> · <span data-num>{formatDate(d.trade_date)}</span> · {brokerName(d.broker_id)}</span>
            </div>
          ) : null}
          {d && originalText(d) ? <div data-num className="text-[12px] text-muted">{originalText(d)}</div> : null}
        </div>
        <span className={`inline-flex shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap ${STATUS[item.status].style}`}>
          {STATUS[item.status].label}
        </span>
      </div>
      {item.price_suggested ? (
        <span className="inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold text-gold [background:color-mix(in_srgb,var(--cauri-gold)_14%,rgba(0,0,0,0.74))]">
          preço sugerido
        </span>
      ) : null}
      {item.messages.length ? (
        <ul className="space-y-0.5 text-[12px]">
          {item.messages.map((m) => (
            <li key={m.text} className={m.level === "error" ? "text-loss" : m.level === "warning" ? "text-gold" : "text-muted"}>{m.text}</li>
          ))}
        </ul>
      ) : null}
      {item.question ? (
        <div className="space-y-2">
          <p className="text-[13px] font-medium text-gold">{item.question.text}</p>
          <div className="flex flex-wrap gap-2">
            {item.question.options.slice(0, 8).map((o) => (
              <GlassButton key={o} disabled={readOnly} onClick={() => onAnswer(o)} className="h-9 px-3 text-[13px] disabled:cursor-not-allowed disabled:opacity-60">
                {item.question!.field === "broker_id" ? brokerName(o) : o}
              </GlassButton>
            ))}
          </div>
        </div>
      ) : null}
      {editable ? (
        editing && d ? (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Field label="Quantidade" htmlFor={`${item.id}-q`}>
              <TextInput id={`${item.id}-q`} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
            </Field>
            <Field label="Preço (R$)" htmlFor={`${item.id}-p`}>
              <TextInput id={`${item.id}-p`} inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
            </Field>
            <Field label="Data" htmlFor={`${item.id}-d`}>
              <TextInput id={`${item.id}-d`} type="date" value={day} onChange={(e) => setDay(e.target.value)} />
            </Field>
            <Field label="Corretora" htmlFor={`${item.id}-b`}>
              <SelectInput id={`${item.id}-b`} value={broker} onChange={(e) => setBroker(e.target.value)}>
                {brokers.data?.map((b) => (
                  <option key={b.id} value={b.id}>{b.name}</option>
                ))}
              </SelectInput>
            </Field>
            <div className="col-span-2 flex gap-2 sm:col-span-4">
              <PrimaryButton
                className="h-9 px-4 text-[13px]"
                onClick={() => {
                  onEdit({
                    ...(d.quantity && quantity ? { quantidade: quantity } : {}),
                    ...(price ? { preco: price } : {}),
                    ...(day ? { data: day } : {}),
                    ...(broker ? { broker_id: broker } : {}),
                  });
                  setEditing(false);
                }}
              >
                Salvar
              </PrimaryButton>
              <GlassButton className="h-9 px-3 text-[13px]" onClick={() => setEditing(false)}>Cancelar</GlassButton>
            </div>
          </div>
        ) : (
          <div className="flex gap-2">
            {d ? (
              <GlassButton className="h-9 px-3 text-[13px]" onClick={() => setEditing(true)}>
                <Pencil className="size-3.5" /> Editar
              </GlassButton>
            ) : null}
            <GlassButton className="h-9 px-3 text-[13px]" onClick={onRemove}>
              <Trash2 className="size-3.5" /> Remover
            </GlassButton>
          </div>
        )
      ) : null}
    </li>
  );
}

function spokenKind(tipo?: string): string {
  if (tipo === "saldo_inicial") return "Saldo inicial";
  if (tipo && tipo in TYPE_LABEL) return TYPE_LABEL[tipo as keyof typeof TYPE_LABEL];
  return "Operação";
}
