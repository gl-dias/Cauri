import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, type OpeningBalanceIn, type OpeningSuggestion } from "@/data/api";
import { formatDate } from "@/lib/format";
import { PrimaryButton } from "@/ui/controls";
import { Field, TextInput } from "@/ui/forms";
import { CardHeader, GlassCard } from "@/ui/GlassCard";

const toBR = (value: string) => value.replace(".", ",");

/**
 * Venda descoberta vira oferta de saldo inicial: data, quantidade e custo médio já
 * preenchidos (o custo é o fechamento do dia, marcado como sugestão). Usado pela
 * importação e pelo assistente; quem chama decide para onde o saldo vai.
 */
export function OpeningSuggestionCard({ suggestion: s, onSubmit, note, compact = false }: {
  suggestion: OpeningSuggestion;
  onSubmit: (body: OpeningBalanceIn) => Promise<unknown>;
  note: string;
  compact?: boolean;
}) {
  const [tradeDate, setTradeDate] = useState(s.trade_date);
  const [quantity, setQuantity] = useState(toBR(s.quantity));
  const [cost, setCost] = useState(s.unit_cost ? toBR(s.unit_cost) : "");
  const add = useMutation({
    mutationFn: () => onSubmit({ ticker: s.ticker, trade_date: tradeDate, quantity, unit_cost: cost, broker_id: s.broker_id }),
  });
  const id = (key: string) => `saldo-${s.ticker}-${key}`;
  const suggested = s.unit_cost !== null && cost === toBR(s.unit_cost);
  const body = (
    <>
      <CardHeader
        title={`Falta saldo de ${s.ticker}`}
        subtitle={`As vendas a partir de ${formatDate(s.first_shortfall)} ficam descobertas: falta saldo de ${s.ticker} que veio de antes.`}
      />
      {s.deposit ? (
        <p className="text-[14px] text-gold">
          Um depósito de {toBR(s.deposit.quantity)} {s.ticker} em {formatDate(s.deposit.day)} explica esse saldo: ele veio de fora. Informe o
          custo médio de quando você comprou.
        </p>
      ) : null}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Data do saldo" htmlFor={id("data")}>
          <TextInput id={id("data")} type="date" value={tradeDate} onChange={(e) => setTradeDate(e.target.value)} />
        </Field>
        <Field label="Quantidade" htmlFor={id("qtd")}>
          <TextInput id={id("qtd")} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </Field>
        <Field label="Custo médio (R$)" htmlFor={id("custo")} hint={suggested && s.cost_note ? s.cost_note : "o que você pagou, em média"}>
          <TextInput id={id("custo")} inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} placeholder="0,00" />
        </Field>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-muted">{note}</p>
        <PrimaryButton disabled={!cost || !quantity || add.isPending} onClick={() => add.mutate()} className="disabled:cursor-not-allowed disabled:opacity-60">
          {add.isPending ? "Conferindo..." : "Incluir saldo inicial e conferir de novo"}
        </PrimaryButton>
      </div>
      {add.error ? (
        <p role="alert" className="text-[13px] text-loss">{add.error instanceof ApiError ? add.error.message : "Sem conexão com a API."}</p>
      ) : null}
    </>
  );
  if (compact) return <div className="glass-inset space-y-4 p-4">{body}</div>;
  return (
    <GlassCard lift={false} className="space-y-4">
      {body}
    </GlassCard>
  );
}
