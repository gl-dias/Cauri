"""Operações do ledger: conferir, gravar, editar e remover (soft delete).

Toda escrita, venha de onde vier, passa por aqui. O fluxo de confirmação é:
``check`` mostra ao usuário o que vai acontecer (erros, duplicados prováveis) e
``post`` grava depois que ele confirma. ``post`` refaz a conferência e recusa se
algo mudou no meio do caminho; as constraints do banco são a última linha.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from cauri_core import AssetClass, FixedIncomeTerms, Movement, MovementType, Origin
from cauri_core.dates import today_sp
from cauri_engine.calc import (
    CdiCurve,
    FixedIncomeBook,
    RedemptionExceedsBalanceError,
    find_oversell,
    in_order,
)
from cauri_ledger import repo
from cauri_ledger.models import (
    DraftCheck,
    DuplicateCandidate,
    Issue,
    IssueCode,
    LedgerValidationError,
    MovementChangeRejectedError,
    MovementDraft,
    MovementNotFoundError,
    MovementPatch,
    PostResult,
)
from cauri_ledger.validation import check_class, check_shape
from cauri_storage import Conn

_ORIGIN_LABELS = {Origin.MANUAL: "Manual", Origin.CHAT: "Chat", Origin.IMPORT: "Planilha"}


@dataclass(slots=True)
class _Resolved:
    """Rascunho com ativo/título resolvido para simulação e gravação."""

    asset_id: UUID | None = None
    asset_class: AssetClass | None = None
    ticker: str | None = None
    instrument_id: UUID | None = None
    instrument_is_new: bool = False
    terms: FixedIncomeTerms | None = None


class Ledger:
    def __init__(self, conn: Conn, *, today: date | None = None) -> None:
        self._conn = conn
        self._today = today

    @property
    def today(self) -> date:
        return self._today or today_sp()

    # Conferência ----------------------------------------------------------------

    def check(
        self, user_id: UUID, drafts: Sequence[MovementDraft], *, origin: Origin
    ) -> list[DraftCheck]:
        conn = self._conn
        errors: list[list[Issue]] = [check_shape(d, self.today) for d in drafts]

        seen: dict[str, int] = {}
        for i, d in enumerate(drafts):
            if d.idempotency_key in seen:
                errors[i].append(
                    Issue(
                        IssueCode.INVALID,
                        "Movimentação repetida no mesmo envio.",
                        "idempotency_key",
                    )
                )
            seen.setdefault(d.idempotency_key, i)

        resolved = self._resolve(user_id, drafts, errors)
        posted = repo.existing_keys(conn, user_id, [d.idempotency_key for d in drafts])

        simulate = [
            i for i, d in enumerate(drafts) if not errors[i] and d.idempotency_key not in posted
        ]
        self._simulate_timeline(user_id, drafts, resolved, simulate, errors)

        checks: list[DraftCheck] = []
        for i, d in enumerate(drafts):
            duplicates: tuple[DuplicateCandidate, ...] = ()
            if not errors[i] and d.idempotency_key not in posted:
                movement = self._as_movement(d, resolved[i], seq=0)
                if movement.asset_id is not None or not resolved[i].instrument_is_new:
                    duplicates = tuple(
                        repo.duplicate_candidates(
                            conn, user_id, origin, d.idempotency_key, movement
                        )
                    )
            checks.append(
                DraftCheck(
                    index=i,
                    draft=d,
                    errors=tuple(errors[i]),
                    duplicates=duplicates,
                    already_posted=posted.get(d.idempotency_key),
                )
            )
        return checks

    def _resolve(
        self, user_id: UUID, drafts: Sequence[MovementDraft], errors: list[list[Issue]]
    ) -> list[_Resolved]:
        conn = self._conn
        tickers = {d.ticker.strip().upper() for d in drafts if d.ticker}
        assets = repo.find_assets(conn, tickers)
        brokers = repo.find_brokers(conn, {d.broker_id for d in drafts if d.broker_id})
        instruments = repo.get_instruments(
            conn, user_id, {d.instrument_id for d in drafts if d.instrument_id}
        )
        new_terms: dict[tuple[Any, ...], UUID] = {}

        result: list[_Resolved] = []
        for i, d in enumerate(drafts):
            r = _Resolved()
            if d.broker_id and d.broker_id not in brokers:
                errors[i].append(
                    Issue(
                        IssueCode.UNKNOWN_BROKER,
                        f"Corretora desconhecida: {d.broker_id}.",
                        "broker_id",
                    )
                )
            if d.ticker:
                ticker = d.ticker.strip().upper()
                asset = assets.get(ticker)
                if asset is None:
                    errors[i].append(
                        Issue(IssueCode.UNKNOWN_ASSET, f"Ativo não encontrado: {ticker}.", "ticker")
                    )
                else:
                    r.asset_id, r.asset_class, r.ticker = asset.id, asset.asset_class, asset.ticker
                    errors[i].extend(check_class(d, asset.asset_class))
            elif d.instrument_id:
                terms = instruments.get(d.instrument_id)
                if terms is None:
                    errors[i].append(
                        Issue(
                            IssueCode.UNKNOWN_INSTRUMENT,
                            "Título de renda fixa não encontrado.",
                            "instrument_id",
                        )
                    )
                else:
                    r.instrument_id, r.terms, r.asset_class = terms.id, terms, AssetClass.RENDA_FIXA
                    if d.broker_id != terms.broker_id:
                        errors[i].append(
                            Issue(
                                IssueCode.INVALID,
                                "A corretora deve ser a mesma do título.",
                                "broker_id",
                            )
                        )
            elif d.fixed_income is not None and not errors[i]:
                fi = d.fixed_income
                existing = repo.find_instrument_by_terms(conn, user_id, fi, d.broker_id)
                if existing is not None:
                    r.instrument_id, r.terms = existing.id, existing
                else:
                    key = (
                        fi.kind,
                        fi.issuer_name.strip(),
                        fi.rate_pct,
                        fi.maturity_date,
                        d.broker_id,
                    )
                    placeholder = new_terms.setdefault(key, uuid4())
                    r.instrument_id, r.instrument_is_new = placeholder, True
                    r.terms = FixedIncomeTerms(
                        id=placeholder,
                        kind=fi.kind,
                        issuer_name=fi.issuer_name.strip(),
                        rate_pct=fi.rate_pct,
                        maturity_date=fi.maturity_date,
                        broker_id=d.broker_id,
                        label=fi.display_label(),
                    )
                r.asset_class = AssetClass.RENDA_FIXA
            result.append(r)
        return result

    @staticmethod
    def _as_movement(
        d: MovementDraft, r: _Resolved, seq: int, movement_id: UUID | None = None
    ) -> Movement:
        return Movement(
            id=movement_id or uuid4(),
            trade_date=d.trade_date,
            type=d.type,
            broker_id=d.broker_id,
            asset_id=r.asset_id,
            instrument_id=r.instrument_id if r.asset_id is None else None,
            quantity=d.quantity,
            unit_price=d.unit_price,
            fees=d.fees,
            amount=d.amount,
            factor=d.factor,
            income_kind=d.income_kind,
            seq=seq,
        )

    def _simulate_timeline(
        self,
        user_id: UUID,
        drafts: Sequence[MovementDraft],
        resolved: list[_Resolved],
        indexes: list[int],
        errors: list[list[Issue]],
    ) -> None:
        """Simula a linha do tempo com os rascunhos e marca os que a quebrariam."""
        if not indexes:
            return
        asset_ids = {resolved[i].asset_id for i in indexes if resolved[i].asset_id}
        instrument_ids = {
            resolved[i].instrument_id
            for i in indexes
            if resolved[i].instrument_id and resolved[i].asset_id is None
        }
        existing = repo.active_movements(
            self._conn, user_id, {a for a in asset_ids if a}, {x for x in instrument_ids if x}
        )
        base_seq = len(existing)
        simulated: dict[UUID, int] = {}
        draft_movements: list[Movement] = []
        for offset, i in enumerate(indexes):
            m = self._as_movement(drafts[i], resolved[i], seq=base_seq + offset)
            simulated[m.id] = i
            draft_movements.append(m)

        tickers = {
            resolved[i].asset_id: resolved[i].ticker for i in indexes if resolved[i].asset_id
        }
        active = list(draft_movements)
        # Vendas descobertas: marca o rascunho culpado, tira da simulação e repete.
        for _ in range(len(active) + 1):
            found = find_oversell([*existing, *active])
            if found is None:
                break
            ticker = tickers.get(found.asset_id) or "o ativo"
            culprit = simulated.get(found.movement_id)
            if culprit is not None:
                errors[culprit].append(
                    Issue(
                        IssueCode.OVERSELL,
                        f"Venda maior que a posição de {ticker} em {found.trade_date:%d/%m/%Y} "
                        f"(disponível: {found.available.normalize():f}).",
                        "quantity",
                    )
                )
            else:
                culprit = self._latest_reducing_draft(
                    active, simulated, found.asset_id, found.trade_date
                )
                if culprit is None:  # pragma: no cover - linha do tempo existente já inválida
                    break
                errors[culprit].append(
                    Issue(
                        IssueCode.OVERSELL,
                        f"Esta movimentação deixa descoberta a venda de {ticker} em "
                        f"{found.trade_date:%d/%m/%Y}.",
                        "quantity",
                    )
                )
            active = [m for m in active if simulated[m.id] != culprit]

        self._check_fixed_income(user_id, resolved, existing, active, simulated, errors)

    @staticmethod
    def _latest_reducing_draft(
        active: list[Movement], simulated: dict[UUID, int], asset_id: UUID, until: date
    ) -> int | None:
        reducing = {MovementType.VENDA, MovementType.GRUPAMENTO}
        candidates = [
            m
            for m in active
            if m.asset_id == asset_id and m.type in reducing and m.trade_date <= until
        ]
        if not candidates:
            return None
        return simulated[in_order(candidates)[-1].id]

    def _check_fixed_income(
        self,
        user_id: UUID,
        resolved: list[_Resolved],
        existing: list[Movement],
        active: list[Movement],
        simulated: dict[UUID, int],
        errors: list[list[Issue]],
    ) -> None:
        by_instrument: dict[UUID, list[Movement]] = defaultdict(list)
        for m in [*existing, *active]:
            if m.instrument_id is not None:
                by_instrument[m.instrument_id].append(m)
        touched = {m.instrument_id for m in active if m.instrument_id is not None}
        if not touched:
            return
        terms: dict[UUID, FixedIncomeTerms] = {
            r.instrument_id: r.terms for r in resolved if r.instrument_id and r.terms
        }
        since = min(m.trade_date for k in touched for m in by_instrument[k])
        curve = CdiCurve(repo.cdi_rates(self._conn, since))
        for instrument_id in touched:
            book = FixedIncomeBook(terms=terms[instrument_id], curve=curve)
            for m in in_order(by_instrument[instrument_id]):
                try:
                    book.apply(m)
                except RedemptionExceedsBalanceError as exc:
                    culprit = simulated.get(m.id)
                    if culprit is not None:
                        errors[culprit].append(
                            Issue(
                                IssueCode.REDEMPTION_EXCEEDS_BALANCE,
                                f"Resgate maior que o saldo bruto do título em {exc.on:%d/%m/%Y}.",
                                "amount",
                            )
                        )
                    break

    # Gravação -------------------------------------------------------------------

    def post(
        self,
        user_id: UUID,
        drafts: Sequence[MovementDraft],
        *,
        origin: Origin,
        origin_ref: UUID | None = None,
        origin_label: str | None = None,
    ) -> PostResult:
        checks = self.check(user_id, drafts, origin=origin)
        if any(not c.ok for c in checks):
            raise LedgerValidationError(checks)

        conn = self._conn
        tickers = {d.ticker.strip().upper() for d in drafts if d.ticker}
        assets = repo.find_assets(conn, tickers)
        created: list[UUID] = []
        already: list[UUID] = []
        for check in checks:
            if check.already_posted is not None:
                already.append(check.already_posted)
                continue
            d = check.draft
            asset_id: UUID | None = None
            instrument_id: UUID | None = None
            if d.ticker:
                asset_id = assets[d.ticker.strip().upper()].id
            elif d.instrument_id:
                instrument_id = d.instrument_id
            else:
                assert d.fixed_income is not None
                instrument_id = repo.upsert_instrument(conn, user_id, d.fixed_income, d.broker_id)
            new_id = repo.insert_movement(
                conn,
                user_id,
                {
                    "trade_date": d.trade_date,
                    "asset_id": asset_id,
                    "instrument_id": instrument_id,
                    "type": d.type.value,
                    "income_kind": d.income_kind.value if d.income_kind else None,
                    "quantity": d.quantity,
                    "unit_price": d.unit_price,
                    "fees": d.fees,
                    "amount": d.amount,
                    "factor": d.factor,
                    "broker_id": d.broker_id,
                    "origin": origin.value,
                    "origin_ref": origin_ref,
                    "origin_label": origin_label or _ORIGIN_LABELS[origin],
                    "idempotency_key": d.idempotency_key,
                    "notes": d.notes,
                },
            )
            if new_id is None:
                existing = repo.existing_keys(conn, user_id, [d.idempotency_key])
                already.append(existing[d.idempotency_key])
            else:
                created.append(new_id)
        return PostResult(created=tuple(created), already_posted=tuple(already))

    # Edição e remoção -----------------------------------------------------------

    def amend(
        self, user_id: UUID, movement_id: UUID, patch: MovementPatch, reason: str | None
    ) -> None:
        conn = self._conn
        row = repo.get_movement(conn, user_id, movement_id)
        if row is None:
            raise MovementNotFoundError(movement_id)
        if row["voided_at"] is not None:
            raise MovementChangeRejectedError(
                [Issue(IssueCode.NOT_ALLOWED, "Movimentação removida não pode ser editada.")]
            )
        current = repo.to_movement(row, seq=0)

        asset_id = current.asset_id
        ticker: str | None = None
        if patch.ticker is not None:
            if current.asset_id is None:
                raise MovementChangeRejectedError(
                    [
                        Issue(
                            IssueCode.NOT_ALLOWED,
                            "Título de renda fixa não muda na edição.",
                            "ticker",
                        )
                    ]
                )
            found = repo.find_assets(conn, {patch.ticker.strip().upper()})
            ref = next(iter(found.values()), None)
            if ref is None:
                raise MovementChangeRejectedError(
                    [
                        Issue(
                            IssueCode.UNKNOWN_ASSET,
                            f"Ativo não encontrado: {patch.ticker}.",
                            "ticker",
                        )
                    ]
                )
            asset_id, ticker = ref.id, ref.ticker
        elif current.asset_id is not None:
            ticker = repo.find_assets_by_id(conn, {current.asset_id})[current.asset_id].ticker

        updated = replace(
            current,
            trade_date=patch.trade_date or current.trade_date,
            asset_id=asset_id,
            broker_id=patch.broker_id or current.broker_id,
            quantity=patch.quantity if patch.quantity is not None else current.quantity,
            unit_price=patch.unit_price if patch.unit_price is not None else current.unit_price,
            fees=patch.fees if patch.fees is not None else current.fees,
            amount=patch.amount if patch.amount is not None else current.amount,
            factor=patch.factor if patch.factor is not None else current.factor,
            income_kind=patch.income_kind or current.income_kind,
        )

        draft = MovementDraft(
            idempotency_key=row["idempotency_key"],
            trade_date=updated.trade_date,
            type=updated.type,
            broker_id=updated.broker_id,
            ticker=ticker,
            instrument_id=updated.instrument_id,
            quantity=updated.quantity,
            unit_price=updated.unit_price,
            fees=updated.fees,
            amount=updated.amount,
            factor=updated.factor,
            income_kind=updated.income_kind,
        )
        issues = check_shape(draft, self.today)
        if updated.broker_id != current.broker_id and not repo.find_brokers(
            conn, {updated.broker_id}
        ):
            issues.append(
                Issue(
                    IssueCode.UNKNOWN_BROKER,
                    f"Corretora desconhecida: {updated.broker_id}.",
                    "broker_id",
                )
            )
        if asset_id is not None and asset_id != current.asset_id:
            ref = repo.find_assets_by_id(conn, {asset_id})[asset_id]
            issues.extend(check_class(draft, ref.asset_class))
        if issues:
            raise MovementChangeRejectedError(issues)

        self._assert_timeline(
            user_id, replace_id=movement_id, with_movement=updated, extra_assets={current.asset_id}
        )

        values: dict[str, Any] = {}
        for column, new, old in (
            ("trade_date", updated.trade_date, current.trade_date),
            ("asset_id", updated.asset_id, current.asset_id),
            ("broker_id", updated.broker_id, current.broker_id),
            ("quantity", updated.quantity, current.quantity),
            ("unit_price", updated.unit_price, current.unit_price),
            ("fees", updated.fees, current.fees),
            ("amount", updated.amount, current.amount),
            ("factor", updated.factor, current.factor),
            (
                "income_kind",
                updated.income_kind.value if updated.income_kind else None,
                current.income_kind.value if current.income_kind else None,
            ),
        ):
            if new != old:
                values[column] = new
        if patch.notes is not None and patch.notes != row["notes"]:
            values["notes"] = patch.notes
        repo.set_change_reason(conn, reason)
        repo.update_movement(conn, user_id, movement_id, values)

    def void(self, user_id: UUID, movement_id: UUID, reason: str) -> None:
        conn = self._conn
        if not reason.strip():
            raise MovementChangeRejectedError(
                [Issue(IssueCode.REQUIRED, "Informe o motivo da remoção.", "reason")]
            )
        row = repo.get_movement(conn, user_id, movement_id)
        if row is None:
            raise MovementNotFoundError(movement_id)
        if row["voided_at"] is not None:
            return  # já removida: idempotente
        current = repo.to_movement(row, seq=0)
        self._assert_timeline(
            user_id, replace_id=movement_id, with_movement=None, extra_assets={current.asset_id}
        )
        repo.void_movement(conn, user_id, movement_id, reason.strip())

    def _assert_timeline(
        self,
        user_id: UUID,
        *,
        replace_id: UUID,
        with_movement: Movement | None,
        extra_assets: set[UUID | None],
    ) -> None:
        conn = self._conn
        asset_ids = {a for a in extra_assets if a is not None}
        instrument_ids: set[UUID] = set()
        if with_movement is not None:
            if with_movement.asset_id is not None:
                asset_ids.add(with_movement.asset_id)
            if with_movement.instrument_id is not None:
                instrument_ids.add(with_movement.instrument_id)
        row = repo.get_movement(conn, user_id, replace_id)
        if row is not None and row["instrument_id"] is not None:
            instrument_ids.add(row["instrument_id"])

        existing = repo.active_movements(conn, user_id, asset_ids, instrument_ids)
        timeline: list[Movement] = []
        for m in existing:
            if m.id == replace_id:
                if with_movement is not None:
                    timeline.append(replace(with_movement, seq=m.seq))
            else:
                timeline.append(m)

        found = find_oversell(timeline)
        if found is not None:
            tickers = repo.find_assets_by_id(conn, {found.asset_id})
            ticker = tickers[found.asset_id].ticker if found.asset_id in tickers else "o ativo"
            raise MovementChangeRejectedError(
                [
                    Issue(
                        IssueCode.OVERSELL,
                        f"A alteração deixa descoberta a venda de {ticker} em "
                        f"{found.trade_date:%d/%m/%Y}.",
                    )
                ]
            )

        if instrument_ids:
            terms = repo.get_instruments(conn, user_id, instrument_ids)
            fi_moves = [m for m in timeline if m.instrument_id is not None]
            if fi_moves:
                curve = CdiCurve(repo.cdi_rates(conn, min(m.trade_date for m in fi_moves)))
                for instrument_id in instrument_ids:
                    book = FixedIncomeBook(terms=terms[instrument_id], curve=curve)
                    try:
                        for m in in_order(x for x in fi_moves if x.instrument_id == instrument_id):
                            book.apply(m)
                    except RedemptionExceedsBalanceError as exc:
                        raise MovementChangeRejectedError(
                            [
                                Issue(
                                    IssueCode.REDEMPTION_EXCEEDS_BALANCE,
                                    "A alteração deixa um resgate maior que o saldo em "
                                    f"{exc.on:%d/%m/%Y}.",
                                )
                            ]
                        ) from exc
