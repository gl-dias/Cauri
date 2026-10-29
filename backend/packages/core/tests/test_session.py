from datetime import date, datetime, time

from cauri_core.dates import SAO_PAULO
from cauri_core.session import closing_call_start, market_close, us_daylight_saving


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=SAO_PAULO)


def test_horario_de_verao_americano_em_2026():
    assert not us_daylight_saving(date(2026, 3, 6))  # sexta antes de 08/03
    assert us_daylight_saving(date(2026, 3, 9))
    assert us_daylight_saving(date(2026, 10, 30))  # última sexta com horário de verão
    assert not us_daylight_saving(date(2026, 11, 2))  # termina no domingo 01/11


def test_com_horario_de_verao_americano_o_pregao_fecha_as_17h():
    # Ofício Circular B3 005/2026: contínua até 16h55, call até 17h00 (desde 09/03/2026).
    assert closing_call_start(date(2026, 10, 30)) == at(date(2026, 10, 30), 16, 55)
    assert market_close(date(2026, 10, 30)) == at(date(2026, 10, 30), 17, 0)


def test_sem_horario_de_verao_americano_o_pregao_fecha_as_18h():
    assert closing_call_start(date(2026, 11, 3)) == at(date(2026, 11, 3), 17, 55)
    assert market_close(date(2026, 11, 3)) == at(date(2026, 11, 3), 18, 0)
    assert market_close(date(2026, 3, 6)) == at(date(2026, 3, 6), 18, 0)
