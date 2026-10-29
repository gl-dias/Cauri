"""Calendário de pregões da B3.

Regra: dias úteis menos os feriados nacionais em que a B3 não abre, mais 24/12 e 31/12
(sem pregão). Desde 2022 a B3 opera nos feriados municipais e estaduais de São Paulo.
O dia 20/11 (Consciência Negra) virou feriado nacional em 2024.

A fonte da verdade histórica são os próprios arquivos COTAHIST (dias com negócio);
esta regra serve para datas futuras e para conferência.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from functools import cache


def easter(year: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


@cache
def b3_holidays(year: int) -> frozenset[date]:
    pascoa = easter(year)
    days = {
        date(year, 1, 1),  # Confraternização Universal
        pascoa - timedelta(days=48),  # Carnaval (segunda)
        pascoa - timedelta(days=47),  # Carnaval (terça)
        pascoa - timedelta(days=2),  # Sexta-feira Santa
        date(year, 4, 21),  # Tiradentes
        date(year, 5, 1),  # Dia do Trabalho
        pascoa + timedelta(days=60),  # Corpus Christi
        date(year, 9, 7),  # Independência
        date(year, 10, 12),  # Nossa Senhora Aparecida
        date(year, 11, 2),  # Finados
        date(year, 11, 15),  # Proclamação da República
        date(year, 12, 24),  # véspera de Natal: sem pregão
        date(year, 12, 25),  # Natal
        date(year, 12, 31),  # último dia do ano: sem pregão
    }
    if year >= 2024:
        days.add(date(year, 11, 20))  # Dia Nacional de Zumbi e da Consciência Negra
    return frozenset(days)


def is_b3_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in b3_holidays(day.year)


def b3_trading_days(start: date, end: date) -> Iterator[date]:
    """Pregões entre ``start`` e ``end``, inclusive."""
    day = start
    while day <= end:
        if is_b3_trading_day(day):
            yield day
        day += timedelta(days=1)


def previous_trading_day(day: date) -> date:
    candidate = day - timedelta(days=1)
    while not is_b3_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate
