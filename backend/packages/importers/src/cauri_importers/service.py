"""Pré-visualização e gravação de uma importação.

``preview`` lê os arquivos, resolve ativos e corretoras, confere tudo no ledger (erros,
já importadas, duplicados prováveis de outras origens) e guarda o lote. Nada vai para
o ledger até ``commit``, que grava as linhas boas e as decisões do usuário sobre os
duplicados, tudo numa transação.

Idempotência: cada linha vira uma chave ``imp:<fonte>:<hash>``, com o hash do conteúdo
normalizado e da ordem de ocorrência entre linhas iguais do mesmo arquivo. Reenviar o
arquivo, ou um export com período sobreposto, cai nas mesmas chaves; duas compras
idênticas no mesmo dia continuam sendo duas.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from cauri_core import CORPORATE_EVENTS, Movement, MovementType, Origin
from cauri_engine.calc import replay
from cauri_importers import brokers as broker_names
from cauri_importers import drafts, fx, registry
from cauri_importers.adapters.mapped import MappedAdapter
from cauri_importers.model import (
    Adapter,
    Item,
    Line,
    PrivateFixedIncome,
    TesouroTitle,
    Ticker,
)
from cauri_importers.privacy import normalize
from cauri_importers.table import FileError, UnknownFormatError, read
from cauri_ledger import (
    CatalogAsset,
    Decision,
    DraftCheck,
    Ledger,
    LedgerValidationError,
    MovementDraft,
    StagedFile,
    StagedRow,
    StoredBatch,
)

MAX_FILES = 10


@dataclass(frozen=True, slots=True)
class Upload:
    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class FileProblem:
    index: int  # posição do arquivo no envio
    message: str
    # Formato desconhecido: nomes das colunas do cabeçalho, para o usuário mapear.
    columns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Preview:
    batch: StoredBatch | None  # None quando nenhum arquivo pôde ser lido
    problems: tuple[FileProblem, ...]
    file_indexes: tuple[int, ...]  # posição no envio de cada arquivo do lote, na ordem


class ImportRejectedError(Exception):
    """Erro de importação com mensagem para a tela."""


class BatchNotFoundError(ImportRejectedError):
    pass


class BatchClosedError(ImportRejectedError):
    pass


class CommitRejectedError(ImportRejectedError):
    """A carteira mudou entre a pré-visualização e a gravação."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__(messages[0] if messages else "Importação recusada.")


@dataclass(frozen=True, slots=True)
class CommitResult:
    created: int
    already_imported: int
    replaced: int
    skipped: int


# Pré-visualização --------------------------------------------------------------------


@dataclass(slots=True)
class _File:
    index: int
    adapter: Adapter
    sha256: str
    size: int
    lines: list[Line]
    label: str = ""


@dataclass(slots=True)
class _Row:
    file: _File
    line: Line
    draft: MovementDraft | None = None
    error: str | None = None
    ignored: str | None = None
    check: DraftCheck | None = None
    notes: list[str] = field(default_factory=list)


def preview(ledger: Ledger, user_id: UUID, uploads: Sequence[Upload]) -> Preview:
    if not uploads:
        raise ImportRejectedError("Envie pelo menos um arquivo.")
    if len(uploads) > MAX_FILES:
        raise ImportRejectedError(f"Envie no máximo {MAX_FILES} arquivos por vez.")

    profiles = ledger.imports.profiles(user_id)
    adapters = registry.adapters_for(profiles)
    files, problems = _read_files(uploads, adapters)
    used = {f.adapter.name for f in files}
    ledger.imports.touch_profiles(
        user_id, [p.id for p in profiles if MappedAdapter(p).name in used]
    )
    if not files:
        return Preview(batch=None, problems=tuple(problems), file_indexes=())

    rows = [_Row(file=f, line=line, notes=list(line.notes)) for f in files for line in f.lines]
    _resolve(ledger, user_id, rows)
    _mark_repeated(rows)

    importable = [r for r in rows if r.draft is not None and r.error is None and r.ignored is None]
    checks = ledger.check(
        user_id,
        [r.draft for r in importable if r.draft],
        origin=Origin.IMPORT,
        by_source=True,
        duplicates_neutral=True,
    )
    for row, check in zip(importable, checks, strict=True):
        row.check = check

    for f in files:
        f.label = _file_label(f)
    store = ledger.imports
    batch_id = store.create_batch(user_id, registry.batch_warnings([f.adapter.name for f in files]))
    for f in files:
        file_id = store.add_file(
            user_id,
            batch_id,
            StagedFile(f.label, f.sha256, f.size, f.adapter.name, f.adapter.version),
        )
        store.add_rows(
            user_id,
            file_id,
            [_staged(i, r) for i, r in enumerate(r for r in rows if r.file is f)],
        )
    batch = store.batch(user_id, batch_id)
    return Preview(
        batch=batch, problems=tuple(problems), file_indexes=tuple(f.index for f in files)
    )


def _read_files(
    uploads: Sequence[Upload], adapters: Sequence[Adapter]
) -> tuple[list[_File], list[FileProblem]]:
    files: list[_File] = []
    problems: list[FileProblem] = []
    seen: dict[str, int] = {}
    for index, upload in enumerate(uploads):
        digest = hashlib.sha256(upload.content).hexdigest()
        if digest in seen:
            problems.append(FileProblem(index, "Arquivo repetido neste envio."))
            continue
        seen[digest] = index
        try:
            detected = read(upload.filename, upload.content, adapters)
        except UnknownFormatError as exc:
            problems.append(FileProblem(index, str(exc), tuple(exc.columns)))
            continue
        except FileError as exc:
            problems.append(FileProblem(index, str(exc)))
            continue
        lines = detected.adapter.parse(detected.rows)
        if not lines:
            problems.append(FileProblem(index, "Nenhuma movimentação encontrada no arquivo."))
            continue
        files.append(_File(index, detected.adapter, digest, len(upload.content), lines))
    return files, problems


def _file_label(f: _File) -> str:
    days = [line.item.trade_date for line in f.lines if line.item]
    if not days:
        return f.adapter.title
    first, last = min(days), max(days)
    return f"{f.adapter.title}, {first:%m/%Y} a {last:%m/%Y}"


def _resolve(ledger: Ledger, user_id: UUID, rows: list[_Row]) -> None:
    """Item -> rascunho do ledger: corretora, ativo, fator dos eventos e chave."""
    brokers = ledger.brokers()
    tickers = {
        r.line.item.asset.code
        for r in rows
        if r.line.item and isinstance(r.line.item.asset, Ticker)
    }
    known = ledger.assets(tickers)
    tesouro: list[CatalogAsset] | None = None
    occurrences: Counter[tuple[str, ...]] = Counter()
    rates = fx.load(ledger, [r.line.item for r in rows if r.line.item and not r.line.error])

    for row in rows:
        line = row.line
        if line.error:
            row.error = line.error
            continue
        if line.ignored or line.item is None:
            row.ignored = line.ignored or "Linha sem movimentação."
            continue
        item = line.item
        broker_id = broker_names.resolve(item.broker, brokers)
        if broker_id is None:
            row.error = f"Corretora não reconhecida: {item.broker}."
            continue
        ticker: str | None = None
        if isinstance(item.asset, Ticker):
            ticker = item.asset.code
            asset = known.get(ticker)
            if asset is not None and not asset.active:
                row.notes.append(f"{ticker} não negocia mais na B3; a posição fica sem preço novo.")
        elif isinstance(item.asset, TesouroTitle):
            if tesouro is None:
                tesouro = ledger.tesouro_titles()
            ticker, problem = _tesouro_ticker(item.asset.text, tesouro)
            if ticker is None:
                row.error = problem
                continue

        parts = _content(row.file.adapter.family, item, broker_id, ticker)
        occurrences[(str(row.file.index), *parts)] += 1
        nth = occurrences[(str(row.file.index), *parts)]
        digest = hashlib.sha256("|".join([*parts, str(nth)]).encode()).hexdigest()
        try:
            conv = fx.convert(item, rates)
        except fx.ConversionError as exc:
            row.error = str(exc)
            continue
        row.notes.extend(conv.notes)
        brl = conv.item
        if brl.type is MovementType.PROVENTO and brl.amount is not None and brl.amount <= 0:
            row.ignored = (
                "Rendimento menor que 1 centavo: não entra como provento (a quantidade "
                "recebida entra na linha de compra)."
            )
            continue
        rate = conv.rate
        row.draft = MovementDraft(
            idempotency_key=f"imp:{row.file.adapter.family}:{digest[:40]}",
            trade_date=item.trade_date,
            type=item.type,
            broker_id=broker_id,
            ticker=ticker,
            fixed_income=item.asset.terms if isinstance(item.asset, PrivateFixedIncome) else None,
            quantity=brl.quantity,
            unit_price=brl.unit_price,
            fees=brl.fees,
            amount=brl.amount,
            factor=brl.factor,
            income_kind=brl.income_kind,
            notes=brl.notes,
            origin_label=row.file.adapter.label,
            orig_currency=rate.currency if rate else None,
            orig_value=(item.unit_price if item.unit_price is not None else item.amount)
            if rate
            else None,
            fx_rate=rate.value if rate else None,
            fx_date=rate.on if rate else None,
            fx_source=rate.source if rate else None,
            fee_asset=conv.fee_asset,
            fee_quantity=conv.fee_quantity,
        )
    _derive_factors(ledger, user_id, rows)


def _content(family: str, item: Item, broker_id: str, ticker: str | None) -> tuple[str, ...]:
    def num(value: Decimal | None) -> str:
        return "" if value is None else format(value.normalize(), "f")

    if isinstance(item.asset, PrivateFixedIncome):
        t = item.asset.terms
        asset = f"rf:{t.kind}:{normalize(t.issuer_name)}:{num(t.rate_pct)}:{t.maturity_date}"
    else:
        asset = ticker or ""
    return (
        family,
        item.trade_date.isoformat(),
        item.type.value,
        asset,
        broker_id,
        num(item.quantity),
        num(item.unit_price),
        num(item.fees),
        num(item.amount),
        num(item.factor),
        num(item.credited),
        item.income_kind.value if item.income_kind else "",
        item.currency,
        item.fee_asset or "",
        num(item.fee_quantity),
        f"{item.fee_paid[0]}:{num(item.fee_paid[1])}" if item.fee_paid else "",
    )


def _tesouro_ticker(text: str, titles: list[CatalogAsset]) -> tuple[str | None, str]:
    """ "Tesouro Selic 2029" -> TD-SELIC-01032029, pelo nome e ano no cadastro."""
    wanted = normalize(text)
    matches = [
        t.ticker
        for t in titles
        if normalize(t.name) == wanted or normalize(t.name).startswith(f"{wanted} (")
    ]
    if len(matches) == 1:
        return matches[0], ""
    if not matches:
        return None, f"Título do Tesouro não encontrado no cadastro: {text}."
    return None, f"Mais de um título do Tesouro com esse nome: {text}. Use o código TD-."


def _derive_factors(ledger: Ledger, user_id: UUID, rows: list[_Row]) -> None:
    """Eventos que chegam com as ações recebidas (B3) viram fator pela posição na véspera.

    A posição soma o que já está no ledger e as linhas anteriores deste mesmo envio.
    """
    pending = [r for r in rows if r.draft and r.line.item and r.line.item.credited is not None]
    if not pending:
        return
    tickers = {r.draft.ticker for r in rows if r.draft and r.draft.ticker}
    ids, existing = ledger.timeline(user_id, tickers)
    drafted: list[tuple[_Row, Movement]] = []
    for r in rows:
        d = r.draft
        if d is None or d.ticker is None or d.ticker not in ids or r.error:
            continue
        if d.type in CORPORATE_EVENTS and d.factor is None:
            continue  # o fator ainda vai ser calculado
        drafted.append((r, _movement(d, ids[d.ticker], seq=len(existing) + len(drafted))))

    for r in sorted(pending, key=lambda x: x.draft.trade_date if x.draft else date.min):
        d, item = r.draft, r.line.item
        assert d is not None
        assert item is not None
        assert item.credited is not None
        asset_id = ids.get(d.ticker or "")
        if asset_id is None:
            continue  # o ledger aponta o ativo desconhecido
        before = d.trade_date - timedelta(days=1)
        timeline = [m for m in existing if m.trade_date <= before]
        timeline += [m for _, m in drafted if m.trade_date <= before]
        book = replay(timeline).get(asset_id)
        held = book.quantity if book else Decimal(0)
        if held <= 0:
            r.error = f"Sem posição de {d.ticker} antes de {d.trade_date:%d/%m/%Y} para o evento."
            r.draft = None
            continue
        factor = _event_factor(d.type, held, item.credited)
        r.draft = replace(d, factor=factor)
        r.notes.append(
            f"Fator calculado pela posição de {held.normalize():f} na véspera: "
            f"{factor.normalize():f}."
        )
        drafted.append((r, _movement(r.draft, asset_id, seq=len(existing) + len(drafted))))


def _event_factor(kind: MovementType, held: Decimal, credited: Decimal) -> Decimal:
    if kind is MovementType.DESDOBRAMENTO:
        return ((held + credited) / held).quantize(Decimal("1e-10"))
    if kind is MovementType.GRUPAMENTO:
        return ((held - credited) / held).quantize(Decimal("1e-10"))
    return (credited / held).quantize(Decimal("1e-10"))  # bonificação


def _movement(d: MovementDraft, asset_id: UUID, seq: int) -> Movement:
    return Movement(
        id=uuid4(),
        trade_date=d.trade_date,
        type=d.type,
        broker_id=d.broker_id,
        asset_id=asset_id,
        quantity=d.quantity,
        unit_price=d.unit_price,
        fees=d.fees,
        amount=d.amount,
        factor=d.factor,
        income_kind=d.income_kind,
        seq=seq,
    )


def _mark_repeated(rows: list[_Row]) -> None:
    """Linha que já está em outro arquivo do mesmo envio não entra duas vezes.

    Mesma fonte (export sobreposto): ignora a repetida. Fontes diferentes (B3 e planilha
    própria) com a mesma operação: erro, para o usuário escolher em envios separados.
    """
    by_key: dict[str, _Row] = {}
    by_operation: dict[tuple[Any, ...], _Row] = {}
    for row in rows:
        d = row.draft
        if d is None or row.error or row.ignored:
            continue
        first = by_key.get(d.idempotency_key)
        if first is not None and first.file is not row.file:
            row.ignored = "Já está em outro arquivo deste envio."
            continue
        by_key.setdefault(d.idempotency_key, row)
        operation = (
            d.ticker or d.fixed_income,
            d.trade_date,
            d.type,
            d.quantity if d.type in {MovementType.COMPRA, MovementType.VENDA} else d.amount,
        )
        other = by_operation.get(operation)
        if other is not None and other.file.adapter.family != row.file.adapter.family:
            row.error = (
                f"Mesma operação da linha {other.line.numbers[0]} de outro arquivo deste envio "
                "(outra fonte). Importe os dois em envios separados para escolher qual manter."
            )
            continue
        by_operation.setdefault(operation, row)


def _staged(position: int, row: _Row) -> StagedRow:
    raw = dict(row.line.raw)
    numbers = row.line.numbers
    info = [{"level": "info", "text": n} for n in row.notes]
    if row.error:
        return StagedRow(
            position,
            numbers,
            raw,
            "error",
            draft=drafts.to_json(row.draft) if row.draft else None,
            idempotency_key=row.draft.idempotency_key if row.draft else None,
            messages=({"level": "error", "text": row.error}, *info),
        )
    if row.ignored or row.draft is None:
        return StagedRow(
            position,
            numbers,
            raw,
            "ignored",
            messages=({"level": "info", "text": row.ignored or "Ignorada."},),
        )
    check = row.check
    assert check is not None
    draft_json = drafts.to_json(row.draft)
    key = row.draft.idempotency_key
    if check.errors:
        return StagedRow(
            position,
            numbers,
            raw,
            "error",
            draft=draft_json,
            idempotency_key=key,
            messages=(*({"level": "error", "text": e.message} for e in check.errors), *info),
        )
    if check.already_posted is not None:
        return StagedRow(
            position,
            numbers,
            raw,
            "already_imported",
            draft=draft_json,
            idempotency_key=key,
            messages=({"level": "info", "text": "Já importada antes."},),
            match_movement_ids=(check.already_posted,),
        )
    if check.duplicates:
        texts = [
            f"Parece a mesma operação já lançada por {dup.origin_label or dup.origin.value} "
            f"em {dup.trade_date:%d/%m/%Y}."
            for dup in check.duplicates
        ]
        return StagedRow(
            position,
            numbers,
            raw,
            "possible_duplicate",
            draft=draft_json,
            idempotency_key=key,
            messages=(*({"level": "warning", "text": t} for t in texts), *info),
            match_movement_ids=tuple(dup.movement_id for dup in check.duplicates),
            decision="keep_existing",
        )
    return StagedRow(
        position,
        numbers,
        raw,
        "ok",
        draft=draft_json,
        idempotency_key=key,
        messages=tuple(info),
        decision="import",
    )


# Gravação ------------------------------------------------------------------------------

_ALLOWED: dict[str, set[str]] = {
    "ok": {"import"},
    "possible_duplicate": {"keep_existing", "replace", "import_new"},
}


def commit(
    ledger: Ledger, user_id: UUID, batch_id: UUID, decisions: Mapping[UUID, Decision]
) -> CommitResult:
    store = ledger.imports
    batch = store.batch(user_id, batch_id)
    if batch is None:
        raise BatchNotFoundError("Importação não encontrada.")
    if batch.status != "preview":
        raise BatchClosedError("Esta importação já foi gravada ou descartada.")

    rows = [r for f in batch.files for r in f.rows]
    by_id = {r.id: r for r in rows}
    unknown = set(decisions) - set(by_id)
    if unknown:
        raise ImportRejectedError("Decisão para uma linha que não é deste lote.")

    chosen: dict[UUID, Decision] = {}
    selected: list[tuple[UUID, MovementDraft]] = []
    replacing: dict[str, UUID] = {}
    skipped = 0
    for row in rows:
        allowed = _ALLOWED.get(row.status)
        if allowed is None:
            if row.id in decisions:
                raise ImportRejectedError("Só linhas boas ou duplicadas recebem decisão.")
            continue
        decision = decisions.get(row.id, row.decision or "import")
        if decision not in allowed:
            raise ImportRejectedError(f"Decisão inválida para a linha {row.line_numbers[0]}.")
        chosen[row.id] = decision
        if decision == "keep_existing":
            skipped += 1
            continue
        assert row.draft is not None
        draft = drafts.from_json(row.draft)
        selected.append((row.id, draft))
        if decision == "replace":
            replacing[draft.idempotency_key] = row.match_movement_ids[0]

    if selected:
        try:
            result = ledger.post(
                user_id,
                [d for _, d in selected],
                origin=Origin.IMPORT,
                origin_ref=batch_id,
                by_source=True,
                replacing=replacing,
                replace_reason="Substituída por uma importação de planilha.",
            )
        except LedgerValidationError as exc:
            raise CommitRejectedError(_messages(exc, selected, by_id)) from exc
        created, already = len(result.created), len(result.already_posted)
    else:
        created = already = 0

    ids = ledger.ids_for_keys(user_id, [d.idempotency_key for _, d in selected])
    store.record_results(
        user_id, chosen, {row_id: ids[d.idempotency_key] for row_id, d in selected}
    )
    store.finish(user_id, batch_id, "committed")
    return CommitResult(
        created=created, already_imported=already, replaced=len(replacing), skipped=skipped
    )


def _messages(
    exc: LedgerValidationError,
    selected: list[tuple[UUID, MovementDraft]],
    by_id: Mapping[UUID, Any],
) -> list[str]:
    out: list[str] = []
    for check in exc.checks:
        if check.ok:
            continue
        row_id = selected[check.index][0]
        line = by_id[row_id].line_numbers[0]
        out.extend(f"Linha {line}: {e.message}" for e in check.errors)
    return out or ["A carteira mudou desde a pré-visualização. Envie os arquivos de novo."]


def discard(ledger: Ledger, user_id: UUID, batch_id: UUID) -> None:
    store = ledger.imports
    if store.batch(user_id, batch_id) is None:
        raise BatchNotFoundError("Importação não encontrada.")
    if not store.finish(user_id, batch_id, "discarded"):
        raise BatchClosedError("Esta importação já foi gravada ou descartada.")
