"""Horário do pregão de ações da B3, que acompanha o horário de verão americano.

O Brasil não tem horário de verão desde 2019 (Brasília é UTC-3 o ano todo), mas a B3
ajusta a grade para casar com a bolsa de Nova York:

* com horário de verão nos EUA (2º domingo de março ao 1º domingo de novembro):
  negociação contínua até 16h55 e call de fechamento até 17h00
  (Ofício Circular B3 005/2026-PRE, vigente desde 09/03/2026);
* sem horário de verão nos EUA: contínua até 17h55 e call até 18h00.

O fechamento oficial sai no fim do call. Se a B3 mudar a política, é aqui que muda.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from cauri_core.dates import SAO_PAULO

NEW_YORK = ZoneInfo("America/New_York")


def us_daylight_saving(day: date) -> bool:
    """Se Nova York está em horário de verão ao meio-dia do dia dado."""
    noon = datetime.combine(day, time(12), tzinfo=NEW_YORK)
    return bool(noon.dst())


def closing_call_start(day: date) -> datetime:
    """Início do call de fechamento das ações (horário de Brasília)."""
    hour = time(16, 55) if us_daylight_saving(day) else time(17, 55)
    return datetime.combine(day, hour, tzinfo=SAO_PAULO)


def market_close(day: date) -> datetime:
    """Fim do call de fechamento: a partir daqui existe preço de fechamento do dia."""
    return closing_call_start(day) + timedelta(minutes=5)
