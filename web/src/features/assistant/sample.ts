/**
 * Conversa gravada para a vitrine do /demo (e para os testes de interface). Dados
 * inventados, no formato que a API devolve. Nenhuma chamada ao backend.
 */
import type { ChatMessage, Conversation, ConversationSummary, ProposalItem } from "@/data/api";

function item(partial: Partial<ProposalItem> & Pick<ProposalItem, "id" | "status">): ProposalItem {
  return {
    kind: "operacao",
    ticker: null,
    asset_name: null,
    question: null,
    price_suggested: null,
    messages: [],
    movement_id: null,
    spoken: null,
    draft: null,
      broker_name: partial.draft?.broker_id === "binance" ? "Binance" : "XP Investimentos",
    ...partial,
  };
}

const draft = (d: Partial<NonNullable<ProposalItem["draft"]>> & Pick<NonNullable<ProposalItem["draft"]>, "type" | "ticker">) => ({
  trade_date: "2026-10-28",
  broker_id: "xp",
  quantity: null,
  unit_price: null,
  amount: null,
  income_kind: null,
  ...d,
});

const at = (minute: number) => `2026-10-28T21:${String(minute).padStart(2, "0")}:00Z`;

const messages: ChatMessage[] = [
  { id: "m1", role: "user", content: "comprei 3 petrobras e vendi 2 itau", input_mode: "voz", created_at: at(10), proposal: null },
  {
    id: "m2",
    role: "assistant",
    content: "Entendi 2 operações. Confira o cartão e confirme.",
    input_mode: null,
    created_at: at(10),
    proposal: {
      id: "p1",
      message_id: "m2",
      status: "confirmed",
      suggestions: [],
      items: [
        item({
          id: "i1", status: "gravado", ticker: "PETR4", asset_name: "Petrobras PN",
          draft: draft({ type: "compra", ticker: "PETR4", quantity: "3", unit_price: "37.95" }),
          price_suggested: { value: "37.95", date: "2026-10-28" },
          messages: [{ level: "warning", text: "Preço não informado: sugestão pelo fechamento de 28/10/2026. Confira antes de confirmar." }],
          movement_id: "x1",
        }),
        item({
          id: "i2", status: "gravado", ticker: "ITUB4", asset_name: "Itaú Unibanco PN",
          draft: draft({ type: "venda", ticker: "ITUB4", quantity: "2", unit_price: "39.60" }),
          movement_id: "x2",
        }),
      ],
    },
  },
  { id: "m3", role: "assistant", content: "Pronto: 2 movimentações gravadas.", input_mode: null, created_at: at(11), proposal: null },
  { id: "m4", role: "user", content: "comprei 0,01 bitcoin a 120 mil dólares", input_mode: "texto", created_at: at(14), proposal: null },
  {
    id: "m5",
    role: "assistant",
    content: "Entendi 1 operação. Confira o cartão e confirme.",
    input_mode: null,
    created_at: at(14),
    proposal: {
      id: "p2",
      message_id: "m5",
      status: "pending",
      suggestions: [],
      items: [
        item({
          id: "i3", status: "ok", ticker: "BTC", asset_name: "Bitcoin",
          draft: draft({
            type: "compra", ticker: "BTC", broker_id: "binance", quantity: "0.01", unit_price: "641040",
            orig_currency: "USD", orig_value: "120000", fx_date: "2026-10-28", fx_source: "ptax",
          }),
          messages: [{ level: "info", text: "Convertido de USD pela PTAX de venda de 28/10/2026 (R$ 5,342)." }],
        }),
      ],
    },
  },
  { id: "m6", role: "user", content: "comprei 1 petrobras a 31 e vendi 40 taesa a 36", input_mode: "texto", created_at: at(18), proposal: null },
  {
    id: "m7",
    role: "assistant",
    content: "Entendi 2 operações. Antes de gravar, preciso de uma resposta no cartão.",
    input_mode: null,
    created_at: at(18),
    proposal: {
      id: "p3",
      message_id: "m7",
      status: "pending",
      suggestions: [
        {
          ticker: "TAEE11", broker_id: "xp", trade_date: "2026-10-27", quantity: "20", first_shortfall: "2026-10-28",
          unit_cost: "35.4", cost_note: "sugestão: fechamento do TAEE11 de 27/10/2026 (R$ 35,4)", deposit: null,
        },
      ],
      items: [
        item({
          id: "i4", status: "pergunta",
          spoken: { tipo: "compra", ativo: "petrobras", quantidade: "1", preco: "31", moeda: null, data: null },
          question: { field: "ticker", text: "Você tem PETR3 e PETR4. Qual delas?", options: ["PETR3", "PETR4"] },
        }),
        item({
          id: "i5", status: "erro", ticker: "TAEE11", asset_name: "Taesa Unit",
          draft: draft({ type: "venda", ticker: "TAEE11", quantity: "40", unit_price: "36" }),
          messages: [{ level: "error", text: "Venda maior que a posição de TAEE11 em 28/10/2026 (disponível: 20)." }],
        }),
      ],
    },
  },
];

export const SAMPLE_CONVERSATION: Conversation = { id: "c1", title: "comprei 3 petrobras e vendi 2 itau", messages };

export const SAMPLE_CONVERSATIONS: ConversationSummary[] = [
  { id: "c1", title: "comprei 3 petrobras e vendi 2 itau", updated_at: at(18) },
  { id: "c0", title: "recebi 48 reais de taesa", updated_at: "2026-10-20T13:02:00Z" },
];
