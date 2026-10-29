"""Datas no fuso de São Paulo, que é onde o pregão e o CDI acontecem."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def now_sp() -> datetime:
    return datetime.now(tz=SAO_PAULO)


def today_sp() -> date:
    return now_sp().date()


def parse_br_date(text: str) -> date:
    """Lê ``dd/mm/aaaa`` (também aceita ``aaaa-mm-dd``)."""
    cleaned = text.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=SAO_PAULO).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {text!r} (use dd/mm/aaaa)")


def month_start(day: date) -> date:
    return day.replace(day=1)


def add_months(day: date, months: int) -> date:
    """Soma meses mantendo o dia quando possível (31/01 + 1 mês = 28 ou 29/02)."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = _days_in_month(year, month)
    return date(year, month, min(day.day, last))


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def days_in_month(day: date) -> int:
    return _days_in_month(day.year, day.month)
