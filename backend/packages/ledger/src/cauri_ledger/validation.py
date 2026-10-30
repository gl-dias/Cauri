"""Regras de formato do ledger, sem banco. Espelham as constraints do Postgres para dar
erros claros antes de chegar lá."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from cauri_core import CORPORATE_EVENTS, AssetClass, MovementType
from cauri_ledger.models import Issue, IssueCode, MovementDraft

MIN_DATE = date(1990, 1, 1)
QUANTITY_PLACES = 10
MONEY_PLACES = 2

_TRADE_TYPES = {MovementType.COMPRA, MovementType.VENDA}
_FIXED_INCOME_TYPES = {MovementType.APORTE, MovementType.RESGATE}


def _places(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _positive(issues: list[Issue], value: Decimal | None, name: str, label: str) -> None:
    if value is None:
        issues.append(Issue(IssueCode.REQUIRED, f"Informe {label}.", name))
    elif value <= 0:
        issues.append(
            Issue(IssueCode.INVALID, f"{label.capitalize()} deve ser maior que zero.", name)
        )


def _absent(issues: list[Issue], value: Decimal | None, name: str, type_: MovementType) -> None:
    if value is not None:
        issues.append(Issue(IssueCode.INVALID, f"Campo {name} não se aplica a {type_}.", name))


def check_shape(draft: MovementDraft, today: date) -> list[Issue]:
    """Formato do rascunho: campos obrigatórios, sinais, casas decimais e datas."""
    issues: list[Issue] = []
    t = draft.type
    is_fixed_income = draft.fixed_income is not None or draft.instrument_id is not None

    if len(draft.idempotency_key) < 8:
        issues.append(
            Issue(IssueCode.INVALID, "Chave de idempotência curta demais.", "idempotency_key")
        )
    if not draft.broker_id:
        issues.append(Issue(IssueCode.REQUIRED, "Informe a corretora.", "broker_id"))

    if draft.trade_date < MIN_DATE:
        issues.append(Issue(IssueCode.INVALID, "Data anterior a 1990.", "trade_date"))
    if draft.trade_date > today and t is not MovementType.PROVENTO:
        issues.append(Issue(IssueCode.FUTURE_DATE, "Data no futuro.", "trade_date"))

    if draft.ticker and is_fixed_income:
        issues.append(
            Issue(
                IssueCode.INVALID,
                "Informe o ticker ou o título de renda fixa, não os dois.",
                "ticker",
            )
        )
    if not draft.ticker and not is_fixed_income:
        issues.append(Issue(IssueCode.REQUIRED, "Informe o ativo.", "ticker"))
    if draft.fixed_income is not None and draft.instrument_id is not None:
        issues.append(
            Issue(IssueCode.INVALID, "Título de renda fixa informado duas vezes.", "instrument_id")
        )

    if t in _TRADE_TYPES:
        if is_fixed_income:
            issues.append(Issue(IssueCode.NOT_ALLOWED, "Renda fixa usa aporte e resgate.", "type"))
        _positive(issues, draft.quantity, "quantity", "a quantidade")
        if draft.unit_price is None:
            issues.append(Issue(IssueCode.REQUIRED, "Informe o preço.", "unit_price"))
        elif draft.unit_price < 0:
            issues.append(Issue(IssueCode.INVALID, "Preço não pode ser negativo.", "unit_price"))
        _absent(issues, draft.amount, "amount", t)
        _absent(issues, draft.factor, "factor", t)
    elif t in _FIXED_INCOME_TYPES:
        if not is_fixed_income:
            issues.append(
                Issue(IssueCode.NOT_ALLOWED, "Aporte e resgate são só para renda fixa.", "type")
            )
        _positive(issues, draft.amount, "amount", "o valor")
        for value, name in (
            (draft.quantity, "quantity"),
            (draft.unit_price, "unit_price"),
            (draft.factor, "factor"),
        ):
            _absent(issues, value, name, t)
    elif t is MovementType.PROVENTO:
        _positive(issues, draft.amount, "amount", "o valor")
        if draft.income_kind is None:
            issues.append(Issue(IssueCode.REQUIRED, "Informe o tipo de provento.", "income_kind"))
        for value, name in (
            (draft.quantity, "quantity"),
            (draft.unit_price, "unit_price"),
            (draft.factor, "factor"),
        ):
            _absent(issues, value, name, t)
    elif t in CORPORATE_EVENTS:
        if is_fixed_income:
            issues.append(
                Issue(
                    IssueCode.NOT_ALLOWED,
                    "Eventos corporativos são só para ações, FIIs e ETFs.",
                    "type",
                )
            )
        _check_factor(issues, draft)
        _absent(issues, draft.quantity, "quantity", t)
        _absent(issues, draft.amount, "amount", t)
        if t is MovementType.BONIFICACAO:
            if draft.unit_price is None:
                issues.append(
                    Issue(
                        IssueCode.REQUIRED,
                        "Informe o custo atribuído por ação (pode ser zero).",
                        "unit_price",
                    )
                )
            elif draft.unit_price < 0:
                issues.append(
                    Issue(IssueCode.INVALID, "Custo atribuído não pode ser negativo.", "unit_price")
                )
        else:
            _absent(issues, draft.unit_price, "unit_price", t)

    if t is not MovementType.PROVENTO and draft.income_kind is not None:
        issues.append(
            Issue(IssueCode.INVALID, "Tipo de provento só vale para provento.", "income_kind")
        )
    if draft.fees < 0:
        issues.append(Issue(IssueCode.INVALID, "Taxas não podem ser negativas.", "fees"))
    elif draft.fees > 0 and t not in _TRADE_TYPES:
        issues.append(Issue(IssueCode.INVALID, "Taxas só se aplicam a compra e venda.", "fees"))

    for value, name, places in (
        (draft.quantity, "quantity", QUANTITY_PLACES),
        (draft.unit_price, "unit_price", QUANTITY_PLACES),
        (draft.factor, "factor", QUANTITY_PLACES),
        (draft.amount, "amount", MONEY_PLACES),
        (draft.fees, "fees", MONEY_PLACES),
    ):
        if value is not None and _places(value) > places:
            issues.append(
                Issue(IssueCode.INVALID, f"Casas decimais demais (máximo {places}).", name)
            )

    fx = (draft.orig_currency, draft.orig_value, draft.fx_rate, draft.fx_date, draft.fx_source)
    if any(v is not None for v in fx) and any(v is None for v in fx):
        issues.append(Issue(IssueCode.INVALID, "Conversão de moeda incompleta.", "fx_rate"))
    if draft.fx_rate is not None and draft.fx_rate <= 0:
        issues.append(Issue(IssueCode.INVALID, "Cotação de conversão inválida.", "fx_rate"))
    if draft.fx_source is not None and draft.fx_source not in {"ptax", "fechamento"}:
        issues.append(Issue(IssueCode.INVALID, "Fonte de cotação desconhecida.", "fx_source"))
    if (draft.fee_asset is None) != (draft.fee_quantity is None) or (
        draft.fee_quantity is not None and draft.fee_quantity <= 0
    ):
        issues.append(Issue(IssueCode.INVALID, "Taxa em outro ativo incompleta.", "fee_asset"))

    if draft.opening_balance and (t is not MovementType.COMPRA or is_fixed_income):
        issues.append(
            Issue(
                IssueCode.NOT_ALLOWED,
                "Saldo inicial é uma compra de ativo negociado (ação, FII, ETF, Tesouro, cripto).",
                "opening_balance",
            )
        )

    fi = draft.fixed_income
    if fi is not None:
        if not fi.issuer_name.strip():
            issues.append(
                Issue(
                    IssueCode.REQUIRED, "Informe o emissor do título.", "fixed_income.issuer_name"
                )
            )
        if fi.rate_pct <= 0 or fi.rate_pct > 1000:
            issues.append(
                Issue(IssueCode.INVALID, "Percentual do CDI inválido.", "fixed_income.rate_pct")
            )
        if fi.maturity_date <= draft.trade_date:
            issues.append(
                Issue(
                    IssueCode.INVALID,
                    "Vencimento deve ser depois da data do aporte.",
                    "fixed_income.maturity_date",
                )
            )
    return issues


def _check_factor(issues: list[Issue], draft: MovementDraft) -> None:
    factor = draft.factor
    if factor is None:
        issues.append(Issue(IssueCode.REQUIRED, "Informe o fator do evento.", "factor"))
        return
    if draft.type is MovementType.DESDOBRAMENTO and factor <= 1:
        issues.append(
            Issue(
                IssueCode.INVALID,
                "No desdobramento o fator é maior que 1 (ex.: 2 = cada ação vira 2).",
                "factor",
            )
        )
    elif draft.type is MovementType.GRUPAMENTO and not 0 < factor < 1:
        issues.append(
            Issue(
                IssueCode.INVALID,
                "No grupamento o fator fica entre 0 e 1 (ex.: 0,1 = 10 viram 1).",
                "factor",
            )
        )
    elif draft.type is MovementType.BONIFICACAO and factor <= 0:
        issues.append(
            Issue(
                IssueCode.INVALID,
                "Na bonificação o fator é maior que zero (ex.: 0,1 = 10%).",
                "factor",
            )
        )


_CORPORATE_CLASSES = frozenset({AssetClass.ACAO, AssetClass.FII, AssetClass.ETF})


def check_class(draft: MovementDraft, asset_class: AssetClass) -> list[Issue]:
    """Combinação entre tipo de movimentação e classe do ativo resolvido."""
    if draft.type in CORPORATE_EVENTS and asset_class not in _CORPORATE_CLASSES:
        return [
            Issue(
                IssueCode.NOT_ALLOWED,
                "Eventos corporativos são só para ações, FIIs e ETFs.",
                "type",
            )
        ]
    return []
