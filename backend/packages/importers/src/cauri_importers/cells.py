"""Conversão de células em datas e números, com mensagens que vão para a tela."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from cauri_core.dates import SAO_PAULO
from cauri_core.money import parse_br_decimal, to_decimal
from cauri_importers.model import Cell

_LEADING_ZERO_DOT = re.compile(r"^-?0\.\d+$")


class LineError(ValueError):
    """Linha que não dá para interpretar. A mensagem vai direto para a tela."""


def text(cell: Cell) -> str | None:
    if cell is None:
        return None
    if isinstance(cell, date):
        return f"{cell:%d/%m/%Y}"
    value = str(cell).strip()
    return value or None


def required_text(cell: Cell, label: str) -> str:
    value = text(cell)
    if value is None:
        raise LineError(f"Falta {label}.")
    return value


def day(cell: Cell, label: str = "a data") -> date:
    if isinstance(cell, date):
        return cell
    value = text(cell)
    if value is None:
        raise LineError(f"Falta {label}.")
    for pattern in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=SAO_PAULO).date()
        except ValueError:
            continue
    raise LineError(f"Data inválida em {label}: {value} (use dd/mm/aaaa).")


def number(cell: Cell, label: str) -> Decimal:
    value = optional_number(cell, label)
    if value is None:
        raise LineError(f"Falta {label}.")
    return value


def optional_number(cell: Cell, label: str) -> Decimal | None:
    if cell is None:
        return None
    if isinstance(cell, Decimal):
        return cell
    if isinstance(cell, date):
        raise LineError(f"Número inválido em {label}.")
    raw = cell.strip()
    if not raw:
        return None
    try:
        # "0.001" é decimal com ponto, não milhar: ninguém escreve um como "0.001".
        if _LEADING_ZERO_DOT.match(raw):
            return to_decimal(raw)
        return parse_br_decimal(raw)
    except ValueError as exc:
        raise LineError(f"Número inválido em {label}: {raw}.") from exc
