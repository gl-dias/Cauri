from datetime import date
from decimal import Decimal

import pytest

from cauri_core.calendar import b3_holidays, easter, is_b3_trading_day, previous_trading_day
from cauri_core.dates import add_months, parse_br_date
from cauri_core.money import format_brl, parse_br_decimal, q2, to_decimal


class TestDinheiro:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1.234,56", "1234.56"),
            ("38,45", "38.45"),
            ("100", "100"),
            ("R$ 1.000.000,01", "1000000.01"),
            ("0,00012345", "0.00012345"),
            ("38.45", "38.45"),
            ("-12,5", "-12.5"),
        ],
    )
    def test_le_numero_brasileiro(self, text, expected):
        assert parse_br_decimal(text) == Decimal(expected)

    @pytest.mark.parametrize("text", ["", "abc", "1,2,3", "1.23.4"])
    def test_recusa_numero_invalido(self, text):
        with pytest.raises(ValueError, match="número"):
            parse_br_decimal(text)

    def test_float_nunca_entra(self):
        with pytest.raises(TypeError):
            to_decimal(0.1)  # type: ignore[arg-type]

    def test_formata_em_reais_pt_br(self):
        assert format_brl(Decimal("1234.56")) == "R$ 1.234,56"
        assert format_brl(Decimal("0.5")) == "R$ 0,50"
        assert format_brl(Decimal("-1000000")) == "-R$ 1.000.000,00"

    def test_arredonda_centavos_meio_para_o_par(self):
        assert q2(Decimal("0.125")) == Decimal("0.12")
        assert q2(Decimal("0.135")) == Decimal("0.14")


class TestDatas:
    def test_le_data_brasileira(self):
        assert parse_br_date("15/03/2026") == date(2026, 3, 15)
        assert parse_br_date("2026-03-15") == date(2026, 3, 15)

    def test_soma_meses_no_fim_do_mes(self):
        assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
        assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


class TestCalendarioB3:
    def test_pascoa(self):
        assert easter(2026) == date(2026, 4, 5)
        assert easter(2025) == date(2025, 4, 20)

    def test_feriados_moveis_de_2026(self):
        holidays = b3_holidays(2026)
        assert date(2026, 2, 16) in holidays  # Carnaval
        assert date(2026, 2, 17) in holidays
        assert date(2026, 4, 3) in holidays  # Sexta-feira Santa
        assert date(2026, 6, 4) in holidays  # Corpus Christi
        assert date(2026, 11, 20) in holidays  # Consciência Negra

    def test_fim_de_semana_e_feriado_nao_tem_pregao(self):
        assert not is_b3_trading_day(date(2026, 3, 7))
        assert not is_b3_trading_day(date(2026, 12, 31))
        assert is_b3_trading_day(date(2026, 7, 9))  # feriado estadual de SP: B3 abre desde 2022

    def test_pregao_anterior_pula_feriado_e_fim_de_semana(self):
        assert previous_trading_day(date(2026, 4, 6)) == date(2026, 4, 2)
