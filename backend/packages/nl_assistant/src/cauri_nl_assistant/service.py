"""Da frase ao cartão de confirmação, e do cartão ao ledger.

``send`` guarda a mensagem, pede ao extrator os campos da frase, resolve cada ativo e monta
o cartão. Com um cartão aberto na conversa, o extrator também recebe as frases anteriores
do usuário, e uma frase que só completa o cartão ("na XP, dia 29") muda aquele cartão, que
desce para a resposta mais recente: a conversa segue de onde parou.

Cada item vira um rascunho do ledger e passa pela mesma conferência da importação e do
lançamento manual (``ledger.check``): erros, duplicados prováveis e venda descoberta, que
vira oferta de saldo inicial. Nada é gravado até ``confirm``.

Os itens guardam o que foi falado e as escolhas do usuário (respostas e edições); o resto
é recalculado a cada passo por ``_rebuild``, então o cartão nunca fica inconsistente.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from cauri_core import AssetClass, IncomeKind, MovementType, Origin
from cauri_core.money import q2
from cauri_ledger import (
    DraftCheck,
    Ledger,
    LedgerValidationError,
    MovementDraft,
    StoredProposal,
    duplicate_texts,
    fx,
    opening,
)
from cauri_nl_assistant.extraction import (
    Complement,
    Extraction,
    ExtractionError,
    Extractor,
    SpokenOp,
)
from cauri_nl_assistant.resolver import Ask, NotFound, Resolved, Resolver, match_broker, normalize

# Moedas que não são posição: pagar com elas não gera contrapartida (como na importação).
NOT_POSITIONS = frozenset({"BRL", "USD"})
_INCOME_BY_CLASS = {
    AssetClass.ACAO: IncomeKind.DIVIDENDO,
    AssetClass.FII: IncomeKind.RENDIMENTO,
    AssetClass.TESOURO: IncomeKind.JUROS,
    AssetClass.CRIPTO: IncomeKind.RENDIMENTO,
}
_PRICE_PLACES = Decimal("1e-10")
_UNSUPPORTED = (
    "O assistente registra compra, venda, provento e saldo inicial de ações, FIIs, Tesouro e "
    "cripto. Para renda fixa e eventos, use o lançamento manual."
)


MAX_TEXT = 500  # caracteres por frase: o bastante para algumas operações, barato no Haiku
DEFAULT_DAILY_LIMIT = 50
CONTEXT_PHRASES = 3  # frases anteriores que vão junto quando há cartão aberto
_NO_OPERATION = (
    "Não encontrei nenhuma operação nessa frase. Tente assim: "
    '"comprei 10 PETR4 a 38,50 ontem" ou "recebi 50 reais de dividendos de itau".'
)
_NO_OPERATION_WITH_CARD = (
    "Não entendi o que mudar no cartão. Diga só o que falta, como "
    '"na XP" ou "foi dia 29", ou responda direto no cartão.'
)
_FIELD_NAMES = {
    "ativo": "ativo",
    "quantidade": "quantidade",
    "preco": "preço",
    "moeda": "moeda",
    "data": "data",
    "corretora": "corretora",
}


class AssistantError(Exception):
    """Pedido recusado, com mensagem para a tela."""


class LimitReachedError(AssistantError):
    """Limite diário de chamadas pagas do usuário."""


class ProposalNotFoundError(AssistantError):
    pass


class ProposalClosedError(AssistantError):
    pass


@dataclass(frozen=True, slots=True)
class Reply:
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    text: str
    proposal_id: UUID | None


# Conversa ----------------------------------------------------------------------------


def send(
    ledger: Ledger,
    user_id: UUID,
    text: str,
    *,
    extractor: Extractor,
    today: date,
    conversation_id: UUID | None = None,
    input_mode: str = "texto",
    daily_limit: int = DEFAULT_DAILY_LIMIT,
) -> Reply:
    text = text.strip()
    if not text:
        raise AssistantError("Escreva ou fale a operação.")
    if len(text) > MAX_TEXT:
        raise AssistantError(
            f"Frase longa demais (máximo {MAX_TEXT} caracteres). Mande uma operação por vez."
        )
    store = ledger.conversations
    if store.usage_on(user_id, "mensagem", today) >= daily_limit:
        raise LimitReachedError(
            f"Você chegou ao limite de {daily_limit} mensagens por hoje. Amanhã libera de novo; "
            "até lá, dá para lançar à mão ou importar uma planilha."
        )
    card: StoredProposal | None = None
    if conversation_id is None:
        conversation_id = store.create(user_id, text[:60])
    elif not store.exists(user_id, conversation_id):
        raise AssistantError("Conversa não encontrada.")
    else:
        card = store.open_proposal(user_id, conversation_id)
    context = store.recent_user_texts(user_id, conversation_id, CONTEXT_PHRASES) if card else []

    # O extrator recebe só o que o usuário escreveu (e as frases anteriores, com cartão
    # aberto) e a data de hoje. Cada chamada fica registrada (tokens), inclusive a que
    # falhou: é ela que conta para o limite e para o custo.
    provider = "regras" if extractor.model == "regras" else "anthropic"
    try:
        extraction = extract_safely(extractor, text, today, context)
    except ExtractionError as exc:
        store.record_usage(
            user_id, provider=provider, kind="mensagem", model=extractor.model, ok=False, day=today
        )
        user_message = store.add_message(
            user_id, conversation_id, "user", text, input_mode=input_mode
        )
        message = store.add_message(user_id, conversation_id, "assistant", str(exc))
        return Reply(conversation_id, user_message, message, str(exc), None)
    store.record_usage(
        user_id,
        provider=provider,
        kind="mensagem",
        model=extraction.model,
        ok=True,
        day=today,
        input_tokens=extraction.input_tokens,
        output_tokens=extraction.output_tokens,
    )
    user_message = store.add_message(
        user_id,
        conversation_id,
        "user",
        text,
        input_mode=input_mode,
        llm_model=extraction.model,
        llm_output=extraction.to_json(),
    )
    if not extraction.ops:
        if card is not None and extraction.complement is not None:
            return _complete(
                ledger, user_id, conversation_id, user_message, card, extraction.complement, today
            )
        reply = _NO_OPERATION if card is None else _NO_OPERATION_WITH_CARD
        message = store.add_message(user_id, conversation_id, "assistant", reply)
        return Reply(conversation_id, user_message, message, reply, None)

    # A chave de cada rascunho usa o id da proposta: confirmar duas vezes não duplica.
    proposal_id = uuid4()
    primaries = [_primary(op, position=i) for i, op in enumerate(extraction.ops)]
    items, suggestions = _rebuild(ledger, user_id, primaries, today, proposal_key=str(proposal_id))
    reply = _summary(items)
    message = store.add_message(user_id, conversation_id, "assistant", reply)
    store.create_proposal(
        user_id, message, items, [s.to_json() for s in suggestions], proposal_id=proposal_id
    )
    return Reply(conversation_id, user_message, message, reply, proposal_id)


def extract_safely(
    extractor: Extractor, text: str, today: date, context: Sequence[str] = ()
) -> Extraction:
    try:
        return extractor.extract(text, today, context)
    except ExtractionError:
        raise
    except Exception as exc:  # erro inesperado do provedor vira mensagem amigável
        raise ExtractionError("O assistente não respondeu agora. Tente de novo.") from exc


def _complete(
    ledger: Ledger,
    user_id: UUID,
    conversation_id: UUID,
    user_message: UUID,
    card: StoredProposal,
    complement: Complement,
    today: date,
) -> Reply:
    """Frase de seguimento: muda o cartão aberto e o traz para a resposta mais recente."""
    store = ledger.conversations
    primaries = [
        {**dict(i), "choices": dict(i.get("choices") or {})}
        for i in card.items
        if i.get("kind") != "contrapartida"
    ]
    waiting = [i for i in primaries if i["status"] in {"pergunta", "erro"}] or primaries
    # A corretora vale para todos os itens pendentes; o resto, só quando há um item só.
    if complement.said == ("corretora",) or len(waiting) == 1:
        targets = waiting
    else:
        reply = "Tem mais de uma operação pendente no cartão. Responda direto nele, item por item."
        message = store.add_message(user_id, conversation_id, "assistant", reply)
        return Reply(conversation_id, user_message, message, reply, None)

    broker = match_broker(ledger.brokers(), complement.corretora) if complement.corretora else None
    for item in targets:
        _apply_complement(item, complement, broker)
    proposal = _save(ledger, user_id, card, primaries, today)

    changed = [_FIELD_NAMES[k] for k in complement.said if k != "corretora" or broker]
    parts = [f"Atualizei o cartão ({_join(changed)})."] if changed else []
    if complement.corretora and broker is None:
        parts.append(f'Não achei a corretora "{complement.corretora}": escolha no cartão.')
    parts.append(_status(proposal.items))
    reply = " ".join(parts)
    message = store.add_message(user_id, conversation_id, "assistant", reply)
    store.move_proposal(user_id, card.id, message)
    return Reply(conversation_id, user_message, message, reply, card.id)


def _apply_complement(item: dict[str, Any], complement: Complement, broker: str | None) -> None:
    spoken = dict(item["spoken"])
    for key, value in complement.to_json().items():
        if value is not None:
            spoken[key] = value
    item["spoken"] = SpokenOp.from_json(spoken).to_json()
    if complement.ativo:
        item["choices"].pop("ticker", None)
    if complement.preco is not None:
        item["choices"].pop("price_from_close", None)
    if broker:
        item["choices"]["broker_id"] = broker
    elif complement.corretora:
        item["choices"].pop("broker_id", None)  # o cartão pergunta de novo


# Ações do cartão -----------------------------------------------------------------------


def answer(
    ledger: Ledger,
    user_id: UUID,
    proposal_id: UUID,
    item_id: str,
    field: str,
    value: str,
    *,
    today: date,
) -> StoredProposal:
    """Resposta a uma pergunta do cartão: qual ticker, ou qual corretora."""
    if field not in {"ticker", "broker_id"}:
        raise AssistantError("Pergunta desconhecida.")

    def change(item: dict[str, Any]) -> None:
        item["choices"][field] = value.strip().upper() if field == "ticker" else value.strip()

    return _update(ledger, user_id, proposal_id, item_id, change, today)


def edit(
    ledger: Ledger,
    user_id: UUID,
    proposal_id: UUID,
    item_id: str,
    changes: Mapping[str, Any],
    *,
    today: date,
) -> StoredProposal:
    """Edição de um item: quantidade, preço, moeda, data, ticker ou corretora."""
    allowed = {"quantidade", "preco", "moeda", "data", "ticker", "broker_id"}
    if set(changes) - allowed:
        raise AssistantError("Campo que não dá para editar no cartão.")

    def change(item: dict[str, Any]) -> None:
        spoken = dict(item["spoken"])
        for key in ("quantidade", "preco", "moeda", "data"):
            if key in changes:
                spoken[key] = changes[key]
        item["spoken"] = SpokenOp.from_json(spoken).to_json()
        for key in ("ticker", "broker_id"):
            if changes.get(key):
                item["choices"][key] = str(changes[key]).strip()
        if "preco" in changes:
            item["choices"].pop("price_from_close", None)

    return _update(ledger, user_id, proposal_id, item_id, change, today)


def remove(
    ledger: Ledger, user_id: UUID, proposal_id: UUID, item_id: str, *, today: date
) -> StoredProposal:
    store = ledger.conversations
    proposal = _pending(store.proposal(user_id, proposal_id))
    primaries = [dict(i) for i in proposal.items if i.get("kind") != "contrapartida"]
    kept = [i for i in primaries if i["id"] != item_id]
    if len(kept) == len(primaries):
        raise AssistantError("Item não encontrado no cartão.")
    return _save(ledger, user_id, proposal, kept, today)


def add_opening_balance(
    ledger: Ledger,
    user_id: UUID,
    proposal_id: UUID,
    *,
    ticker: str,
    trade_date: date,
    quantity: Decimal,
    unit_cost: Decimal,
    broker_id: str,
    today: date,
) -> StoredProposal:
    """Inclui no cartão um saldo inicial para cobrir uma venda descoberta."""
    store = ledger.conversations
    proposal = _pending(store.proposal(user_id, proposal_id))
    if quantity <= 0 or unit_cost < 0:
        raise AssistantError("Informe quantidade maior que zero e custo médio.")
    primaries = [dict(i) for i in proposal.items if i.get("kind") != "contrapartida"]
    spoken = SpokenOp(
        tipo="saldo_inicial",
        ativo=ticker.strip().upper(),
        quantidade=quantity,
        preco=unit_cost,
        moeda="BRL",
        data=trade_date,
    )
    item = _primary(spoken, position=len(primaries))
    item["choices"] = {"ticker": ticker.strip().upper(), "broker_id": broker_id}
    return _save(ledger, user_id, proposal, [*primaries, item], today)


def confirm(ledger: Ledger, user_id: UUID, proposal_id: UUID, *, today: date) -> StoredProposal:
    """Grava o cartão no ledger, tudo ou nada. Pendência (pergunta ou erro) impede."""
    store = ledger.conversations
    proposal = _pending(store.proposal(user_id, proposal_id))
    items = [dict(i) for i in proposal.items]
    if not items:
        raise AssistantError("O cartão está vazio.")
    pending = [i for i in items if i["status"] not in {"ok", "duplicado"}]
    if pending:
        raise AssistantError(
            "Resolva as pendências do cartão antes de confirmar (responda ou remova o item)."
        )
    drafts = [_draft_from(i) for i in items]
    try:
        ledger.post(user_id, drafts, origin=Origin.CHAT, origin_ref=proposal.message_id)
    except LedgerValidationError as exc:
        raise AssistantError(
            "A carteira mudou desde o cartão. Confira de novo: " + str(exc)
        ) from exc
    ids = ledger.ids_for_keys(user_id, [d.idempotency_key for d in drafts])
    for item, d in zip(items, drafts, strict=True):
        item["status"] = "gravado"
        item["movement_id"] = str(ids[d.idempotency_key])
    store.save_proposal(user_id, proposal_id, items, [], "confirmed")
    conversation = store.conversation_of(user_id, proposal.message_id)
    assert conversation is not None
    count = len(items)
    store.add_message(
        user_id,
        conversation,
        "assistant",
        "Pronto: 1 movimentação gravada."
        if count == 1
        else f"Pronto: {count} movimentações gravadas.",
    )
    result = store.proposal(user_id, proposal_id)
    assert result is not None
    return result


def cancel(ledger: Ledger, user_id: UUID, proposal_id: UUID) -> StoredProposal:
    store = ledger.conversations
    proposal = _pending(store.proposal(user_id, proposal_id))
    store.save_proposal(user_id, proposal_id, proposal.items, [], "cancelled")
    result = store.proposal(user_id, proposal_id)
    assert result is not None
    return result


# Montagem do cartão --------------------------------------------------------------------


def _primary(op: SpokenOp, position: int) -> dict[str, Any]:
    return {
        "id": f"i{position + 1}-{uuid4().hex[:6]}",
        "kind": "saldo_inicial" if op.tipo == "saldo_inicial" else "operacao",
        "spoken": op.to_json(),
        "choices": {},
    }


def _rebuild(
    ledger: Ledger,
    user_id: UUID,
    primaries: Sequence[Mapping[str, Any]],
    today: date,
    *,
    proposal_key: str,
) -> tuple[list[dict[str, Any]], list[opening.Suggestion]]:
    """Recalcula o cartão inteiro a partir do que foi falado e das escolhas do usuário."""
    resolver = Resolver(ledger, user_id)
    items: list[dict[str, Any]] = []
    for primary in primaries:
        items.extend(_build(ledger, user_id, resolver, dict(primary), today, proposal_key))

    with_draft = [i for i in items if i.get("draft") and i["status"] == "pendente"]
    drafts = [_draft_from(i) for i in with_draft]
    checks = ledger.check(user_id, drafts, origin=Origin.CHAT) if drafts else []
    for item, check in zip(with_draft, checks, strict=True):
        _apply_check(item, check)
    for item in items:
        if item["status"] == "pendente":
            item["status"] = "ok"
    suggestions = opening.suggest(
        ledger, user_id, list(zip(drafts, checks, strict=True)), deposits=[]
    )
    return items, suggestions


def _build(
    ledger: Ledger,
    user_id: UUID,
    resolver: Resolver,
    item: dict[str, Any],
    today: date,
    proposal_key: str,
) -> list[dict[str, Any]]:
    """Um item falado vira o item do cartão (e a contrapartida em cripto, quando há)."""
    op = SpokenOp.from_json(item["spoken"])
    choices: dict[str, Any] = dict(item.get("choices") or {})
    item.update(
        choices=choices,
        status="pendente",
        draft=None,
        question=None,
        messages=[],
        price_suggested=None,
        ticker=None,
        asset_name=None,
        movement_id=None,
    )
    messages: list[dict[str, str]] = item["messages"]

    if op.tipo == "outro":
        return [_fail(item, _UNSUPPORTED)]

    resolution = (
        _chosen(ledger, choices["ticker"]) if choices.get("ticker") else resolver.resolve(op.ativo)
    )
    if isinstance(resolution, NotFound):
        return [_fail(item, resolution.text)]
    if isinstance(resolution, Ask):
        item["status"] = "pergunta"
        item["question"] = {
            "field": "ticker",
            "text": resolution.text,
            "options": list(resolution.options),
        }
        return [item]
    item["ticker"], item["asset_name"] = resolution.ticker, resolution.name
    asset_class = resolution.asset_class

    trade_date = op.data or today
    if op.data is None:
        messages.append({"level": "info", "text": "Sem data na frase: vale hoje."})

    broker = choices.get("broker_id")
    if broker is None and op.corretora:
        broker = match_broker(ledger.brokers(), op.corretora)
        if broker is None:
            item["status"] = "pergunta"
            item["question"] = {
                "field": "broker_id",
                "text": f'Não achei a corretora "{op.corretora}". Qual delas?',
                "options": _broker_options(ledger, asset_class),
            }
            return [item]
    broker = broker or _broker_for(ledger, user_id, resolution, asset_class)
    if broker is None:
        item["status"] = "pergunta"
        item["question"] = {
            "field": "broker_id",
            "text": "Em qual corretora?",
            "options": _broker_options(ledger, asset_class),
        }
        return [item]
    item["choices"]["broker_id"] = broker
    item["broker_name"] = ledger.brokers().get(broker, broker)

    currency = op.moeda or "BRL"
    key = f"chat:{proposal_key}:{item['id']}"
    opening_balance = op.tipo == "saldo_inicial"

    if op.tipo == "provento":
        if op.preco is None:
            return [_fail(item, "Diga o valor recebido (ex.: recebi 50 reais de itau).")]
        try:
            rate = _rate(ledger, currency, trade_date, messages)
        except _NoRateError as exc:
            return [_fail(item, str(exc))]
        amount = q2(op.preco * (rate.value if rate else 1))
        draft = MovementDraft(
            idempotency_key=key,
            trade_date=trade_date,
            type=MovementType.PROVENTO,
            broker_id=broker,
            ticker=resolution.ticker,
            amount=amount,
            income_kind=_INCOME_BY_CLASS.get(asset_class, IncomeKind.DIVIDENDO),
            **_orig(rate, op.preco),
        )
        item["draft"] = _draft_json(draft)
        return [item]

    if op.quantidade is None or op.quantidade <= 0:
        return [_fail(item, "Diga a quantidade.")]
    price = op.preco
    if price is None:
        close = ledger.last_close(resolution.ticker, trade_date)
        if close is None:
            return [_fail(item, "Diga o preço: não há fechamento recente para sugerir.")]
        price, currency = close[0], "BRL"
        item["price_suggested"] = {"value": _text(close[0]), "date": close[1].isoformat()}
        messages.append(
            {
                "level": "warning",
                "text": f"Preço não informado: sugestão pelo fechamento de {close[1]:%d/%m/%Y}."
                " Confira antes de confirmar.",
            }
        )
    try:
        rate = _rate(ledger, currency, trade_date, messages)
    except _NoRateError as exc:
        return [_fail(item, str(exc))]
    unit_price = (price * (rate.value if rate else 1)).quantize(_PRICE_PLACES)
    buy = op.tipo in {"compra", "saldo_inicial"}
    draft = MovementDraft(
        idempotency_key=key,
        trade_date=trade_date,
        type=MovementType.COMPRA if buy else MovementType.VENDA,
        broker_id=broker,
        ticker=resolution.ticker,
        quantity=op.quantidade,
        unit_price=unit_price,
        origin_label="Saldo inicial" if opening_balance else None,
        opening_balance=opening_balance,
        **_orig(rate, price),
    )
    item["draft"] = _draft_json(draft)
    out = [item]

    if currency not in NOT_POSITIONS and not opening_balance and rate is not None:
        # Pagar com USDT (ou outra cripto) é vender USDT, como na importação.
        total = op.quantidade * price
        leg = MovementDraft(
            idempotency_key=f"{key}:contrapartida",
            trade_date=trade_date,
            type=MovementType.VENDA if buy else MovementType.COMPRA,
            broker_id=broker,
            ticker=currency,
            quantity=total,
            unit_price=rate.value.quantize(_PRICE_PLACES),
            **_orig(rate, Decimal(1)),
        )
        out.append(
            {
                "id": f"{item['id']}-c",
                "kind": "contrapartida",
                "parent": item["id"],
                "spoken": None,
                "choices": {},
                "status": "pendente",
                "draft": _draft_json(leg),
                "question": None,
                "price_suggested": None,
                "ticker": currency,
                "asset_name": None,
                "movement_id": None,
                "messages": [
                    {
                        "level": "info",
                        "text": f"Contrapartida: {_text(total)} {currency} "
                        f"{'pagos na compra' if buy else 'recebidos na venda'} de "
                        f"{resolution.ticker}.",
                    }
                ],
            }
        )
    return out


def _chosen(ledger: Ledger, ticker: str) -> Resolved | NotFound:
    """Ticker escolhido pelo usuário (resposta ou edição)."""
    asset = ledger.assets({ticker}).get(ticker.strip().upper())
    if asset is None:
        return NotFound(f"Não achei o ticker {ticker.upper()} no cadastro.")
    return Resolved(asset.ticker, asset.asset_class, asset.name)


def _broker_for(
    ledger: Ledger, user_id: UUID, resolution: Resolved, asset_class: AssetClass
) -> str | None:
    """Onde o usuário tem o ativo (se for um lugar só); senão a corretora mais recente
    daquela classe; senão a mais recente de todas. Editável no cartão."""
    held = ledger.holdings(user_id, [resolution.ticker]).get(resolution.ticker, {})
    if len(held) == 1:
        return next(iter(held))
    for brokers in (
        ledger.recent_brokers(user_id, asset_class.value),
        ledger.recent_brokers(user_id),
    ):
        if brokers:
            return brokers[0]
    return None


def _broker_options(ledger: Ledger, asset_class: AssetClass) -> list[str]:
    """Todas as que fazem sentido para a classe: corretoras, bancos e, só em cripto, as
    exchanges (que vêm primeiro). Em cada grupo, ordem alfabética."""
    names, kinds = ledger.brokers(), ledger.broker_kinds()
    order = (
        ("exchange", "corretora", "banco")
        if asset_class is AssetClass.CRIPTO
        else ("corretora", "banco")
    )
    return sorted(
        (b for b in names if kinds.get(b) in order),
        key=lambda b: (order.index(kinds[b]), normalize(names[b])),
    )


class _NoRateError(Exception):
    pass


def _rate(
    ledger: Ledger, currency: str, day: date, messages: list[dict[str, str]]
) -> fx.Rate | None:
    """Cotação da moeda no dia, pela mesma regra da importação (None para real)."""
    if currency == "BRL":
        return None
    rate = fx.rate_or_none(ledger, currency, day)
    if rate is None:
        raise _NoRateError(f"Sem cotação de {currency} até {day:%d/%m/%Y} para converter.")
    messages.append(
        {"level": "info", "text": f"Convertido de {currency} pela {rate.describe(day)}."}
    )
    return rate


def _orig(rate: fx.Rate | None, value: Decimal) -> dict[str, Any]:
    if rate is None:
        return {}
    return {
        "orig_currency": rate.currency,
        "orig_value": value,
        "fx_rate": rate.value,
        "fx_date": rate.on,
        "fx_source": rate.source,
    }


def _fail(item: dict[str, Any], text: str) -> dict[str, Any]:
    item["status"] = "erro"
    item["messages"].append({"level": "error", "text": text})
    return item


def _apply_check(item: dict[str, Any], check: DraftCheck) -> None:
    if check.errors:
        item["status"] = "erro"
        item["messages"].extend(
            {"level": "error", "text": e.message, "code": e.code.value} for e in check.errors
        )
    elif check.already_posted is not None:
        item["status"] = "erro"
        item["messages"].append({"level": "error", "text": "Já gravada antes."})
    elif check.duplicates:
        item["status"] = "duplicado"
        item["messages"].extend(
            {"level": "warning", "text": text}
            for text in duplicate_texts(check.duplicates, " Confirme só se for outra.")
        )


def _summary(items: Sequence[Mapping[str, Any]]) -> str:
    count = sum(i.get("kind") != "contrapartida" for i in items)
    head = "Entendi 1 operação." if count == 1 else f"Entendi {count} operações."
    return f"{head} {_status(items)}"


def _status(items: Sequence[Mapping[str, Any]]) -> str:
    if any(i["status"] == "pergunta" for i in items):
        return "Antes de gravar, preciso de uma resposta no cartão."
    if any(i["status"] == "erro" for i in items):
        return "Tem pendência no cartão: confira antes de confirmar."
    return "Confira o cartão e confirme."


def _join(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} e {items[-1]}"


def _update(
    ledger: Ledger,
    user_id: UUID,
    proposal_id: UUID,
    item_id: str,
    change: Any,
    today: date,
) -> StoredProposal:
    store = ledger.conversations
    proposal = _pending(store.proposal(user_id, proposal_id))
    primaries = [
        {**dict(i), "choices": dict(i.get("choices") or {})}
        for i in proposal.items
        if i.get("kind") != "contrapartida"
    ]
    target = next((i for i in primaries if i["id"] == item_id), None)
    if target is None:
        raise AssistantError("Item não encontrado no cartão.")
    change(target)
    return _save(ledger, user_id, proposal, primaries, today)


def _save(
    ledger: Ledger,
    user_id: UUID,
    proposal: StoredProposal,
    primaries: Sequence[Mapping[str, Any]],
    today: date,
) -> StoredProposal:
    items, suggestions = _rebuild(ledger, user_id, primaries, today, proposal_key=str(proposal.id))
    store = ledger.conversations
    store.save_proposal(user_id, proposal.id, items, [s.to_json() for s in suggestions])
    result = store.proposal(user_id, proposal.id)
    assert result is not None
    return result


def _pending(proposal: StoredProposal | None) -> StoredProposal:
    if proposal is None:
        raise ProposalNotFoundError("Cartão não encontrado.")
    if proposal.status != "pending":
        raise ProposalClosedError("Este cartão já foi confirmado ou cancelado.")
    return proposal


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _draft_json(d: MovementDraft) -> dict[str, Any]:
    return {
        "idempotency_key": d.idempotency_key,
        "trade_date": d.trade_date.isoformat(),
        "type": d.type.value,
        "broker_id": d.broker_id,
        "ticker": d.ticker,
        "quantity": _text(d.quantity) if d.quantity is not None else None,
        "unit_price": _text(d.unit_price) if d.unit_price is not None else None,
        "amount": _text(d.amount) if d.amount is not None else None,
        "income_kind": d.income_kind.value if d.income_kind else None,
        "origin_label": d.origin_label,
        "opening_balance": d.opening_balance,
        "orig_currency": d.orig_currency,
        "orig_value": _text(d.orig_value) if d.orig_value is not None else None,
        "fx_rate": _text(d.fx_rate) if d.fx_rate is not None else None,
        "fx_date": d.fx_date.isoformat() if d.fx_date else None,
        "fx_source": d.fx_source,
    }


def _draft_from(item: Mapping[str, Any]) -> MovementDraft:
    d = item["draft"]

    def dec(key: str) -> Decimal | None:
        return Decimal(d[key]) if d.get(key) is not None else None

    return MovementDraft(
        idempotency_key=d["idempotency_key"],
        trade_date=date.fromisoformat(d["trade_date"]),
        type=MovementType(d["type"]),
        broker_id=d["broker_id"],
        ticker=d["ticker"],
        quantity=dec("quantity"),
        unit_price=dec("unit_price"),
        amount=dec("amount"),
        income_kind=IncomeKind(d["income_kind"]) if d.get("income_kind") else None,
        origin_label=d.get("origin_label"),
        opening_balance=bool(d.get("opening_balance")),
        orig_currency=d.get("orig_currency"),
        orig_value=dec("orig_value"),
        fx_rate=dec("fx_rate"),
        fx_date=date.fromisoformat(d["fx_date"]) if d.get("fx_date") else None,
        fx_source=d.get("fx_source"),
    )
