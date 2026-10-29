from datetime import date
from decimal import Decimal

from cauri_core import FiKind, IncomeKind, MovementType
from cauri_ledger import FixedIncomeDraft, IssueCode, MovementDraft
from cauri_ledger.validation import check_shape

TODAY = date(2026, 10, 29)


def draft(**overrides):
    base = {
        "idempotency_key": "chave-de-teste-1",
        "trade_date": date(2026, 10, 1),
        "type": MovementType.COMPRA,
        "broker_id": "corretora-a",
        "ticker": "PETR4",
        "quantity": Decimal(10),
        "unit_price": Decimal("38.45"),
    }
    base.update(overrides)
    return MovementDraft(**base)


def codes(d):
    return {(i.code, i.field) for i in check_shape(d, TODAY)}


def test_compra_valida_nao_tem_problemas():
    assert check_shape(draft(), TODAY) == []


def test_compra_sem_quantidade_e_sem_preco():
    assert codes(draft(quantity=None, unit_price=None)) == {
        (IssueCode.REQUIRED, "quantity"),
        (IssueCode.REQUIRED, "unit_price"),
    }


def test_quantidade_negativa_e_zero_sao_invalidas():
    assert (IssueCode.INVALID, "quantity") in codes(draft(quantity=Decimal(0)))
    assert (IssueCode.INVALID, "quantity") in codes(draft(quantity=Decimal(-1)))


def test_data_no_futuro_so_para_provento():
    assert (IssueCode.FUTURE_DATE, "trade_date") in codes(draft(trade_date=date(2026, 11, 5)))
    provento = draft(
        type=MovementType.PROVENTO,
        trade_date=date(2026, 11, 5),
        quantity=None,
        unit_price=None,
        amount=Decimal("12.50"),
        income_kind=IncomeKind.DIVIDENDO,
    )
    assert check_shape(provento, TODAY) == []


def test_aporte_exige_titulo_de_renda_fixa():
    aporte = draft(type=MovementType.APORTE, quantity=None, unit_price=None, amount=Decimal(1000))
    assert (IssueCode.NOT_ALLOWED, "type") in codes(aporte)


def test_aporte_em_cdb_valido():
    aporte = draft(
        type=MovementType.APORTE,
        ticker=None,
        quantity=None,
        unit_price=None,
        amount=Decimal(1000),
        fixed_income=FixedIncomeDraft(FiKind.CDB, "Banco X", Decimal(110), date(2028, 10, 1)),
    )
    assert check_shape(aporte, TODAY) == []


def test_vencimento_antes_do_aporte_e_invalido():
    aporte = draft(
        type=MovementType.APORTE,
        ticker=None,
        quantity=None,
        unit_price=None,
        amount=Decimal(1000),
        fixed_income=FixedIncomeDraft(FiKind.CDB, "Banco X", Decimal(110), date(2026, 9, 1)),
    )
    assert (IssueCode.INVALID, "fixed_income.maturity_date") in codes(aporte)


def test_fator_de_cada_evento_corporativo():
    split = draft(
        type=MovementType.DESDOBRAMENTO, quantity=None, unit_price=None, factor=Decimal("0.5")
    )
    grupamento = draft(
        type=MovementType.GRUPAMENTO, quantity=None, unit_price=None, factor=Decimal(2)
    )
    bonus_sem_custo = draft(
        type=MovementType.BONIFICACAO, quantity=None, unit_price=None, factor=Decimal("0.1")
    )
    assert (IssueCode.INVALID, "factor") in codes(split)
    assert (IssueCode.INVALID, "factor") in codes(grupamento)
    assert (IssueCode.REQUIRED, "unit_price") in codes(bonus_sem_custo)


def test_taxa_so_em_compra_e_venda():
    provento = draft(
        type=MovementType.PROVENTO,
        quantity=None,
        unit_price=None,
        amount=Decimal(10),
        income_kind=IncomeKind.JCP,
        fees=Decimal(1),
    )
    assert (IssueCode.INVALID, "fees") in codes(provento)


def test_casas_decimais_alem_do_banco_sao_recusadas_em_vez_de_arredondadas():
    assert (IssueCode.INVALID, "fees") in codes(draft(fees=Decimal("1.234")))
    assert (IssueCode.INVALID, "quantity") in codes(draft(quantity=Decimal("0.00000000001")))
    assert check_shape(draft(quantity=Decimal("0.0000000001")), TODAY) == []  # 10 casas (cripto)
