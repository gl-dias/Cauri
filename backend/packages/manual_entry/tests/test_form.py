from datetime import date
from decimal import Decimal

import pytest

from cauri_core import FiKind, MovementType
from cauri_manual_entry import FormError, ManualEntryForm, ManualPatchForm, to_draft, to_patch


def form(**overrides):
    base = {
        "client_key": "0b6f6f5e-6a7d-4c1e-9d1b-1f2a3b4c5d6e",  # gitleaks:allow (UUID de teste)
        "type": MovementType.COMPRA,
        "trade_date": date(2026, 10, 1),
        "broker_id": " corretora-a ",
        "ticker": " petr4 ",
        "quantity": "100",
        "unit_price": "38,45",
        "fees": "4,90",
    }
    base.update(overrides)
    return ManualEntryForm(**base)


def test_numeros_em_formato_brasileiro_viram_decimal():
    draft = to_draft(form(unit_price="1.234,56"))
    assert draft.unit_price == Decimal("1234.56")
    assert draft.fees == Decimal("4.90")
    assert draft.quantity == Decimal(100)


def test_ticker_e_corretora_normalizados_e_chave_com_prefixo_da_origem():
    draft = to_draft(form())
    assert draft.ticker == "PETR4"
    assert draft.broker_id == "corretora-a"
    assert draft.idempotency_key == "manual:0b6f6f5e-6a7d-4c1e-9d1b-1f2a3b4c5d6e"


def test_taxa_vazia_vira_zero():
    assert to_draft(form(fees="")).fees == 0


def test_numero_invalido_aponta_o_campo():
    with pytest.raises(FormError) as exc:
        to_draft(form(quantity="dez"))
    assert exc.value.field == "quantity"


def test_aporte_em_cdb_monta_o_titulo():
    draft = to_draft(
        form(
            type=MovementType.APORTE,
            ticker=None,
            quantity=None,
            unit_price=None,
            fees=None,
            amount="5.000,00",
            fi_kind=FiKind.CDB,
            fi_issuer="Banco Y",
            fi_rate_pct="110",
            fi_maturity=date(2028, 10, 2),
        )
    )
    assert draft.amount == Decimal("5000.00")
    assert draft.fixed_income is not None
    assert draft.fixed_income.rate_pct == 110
    assert draft.fixed_income.display_label() == "CDB Banco Y 110% CDI 10/2028"


def test_titulo_incompleto_avisa_o_que_falta():
    with pytest.raises(FormError) as exc:
        to_draft(form(type=MovementType.APORTE, ticker=None, amount="100", fi_kind=FiKind.LCI))
    assert exc.value.field == "fi_issuer"


def test_edicao_so_leva_o_que_foi_preenchido():
    patch = to_patch(ManualPatchForm(fees="5,10"))
    assert patch.fees == Decimal("5.10")
    assert patch.quantity is None
    assert patch.trade_date is None
