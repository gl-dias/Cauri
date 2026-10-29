"""Conversão de células em datas e números, com mensagens que vão para a tela."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from cauri_core.dates import SAO_PAULO
from cauri_core.money import parse_br_decimal, to_decimal
from cauri_importers.model import Cell

_LEADING_ZERO_DOT = re.compile(r"^-?0\.\d+$")
_US_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_AMOUNT_COIN = re.compile(r"^(-?[\d.,]+)\s*([A-Z][A-Z0-9]{0,11})$")

DATE_FORMATS = {
    "dd/mm/aaaa": ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y"),
    "aaaa-mm-dd": ("%Y-%m-%d", "%Y/%m/%d"),
    "mm/dd/aaaa": ("%m/%d/%Y", "%m/%d/%y"),
}


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


def day(cell: Cell, label: str = "a data", date_format: str = "dd/mm/aaaa") -> date:
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    value = text(cell)
    if value is None:
        raise LineError(f"Falta {label}.")
    head = value.split()[0]  # "15/03/2026 10:32" vale pela data
    patterns = DATE_FORMATS.get(date_format, DATE_FORMATS["dd/mm/aaaa"])
    if date_format == "dd/mm/aaaa":
        patterns = (*patterns, "%Y-%m-%d")
    for pattern in patterns:
        try:
            return datetime.strptime(head, pattern).replace(tzinfo=SAO_PAULO).date()
        except ValueError:
            continue
    raise LineError(f"Data inválida em {label}: {value} (esperado {date_format}).")


def utc_day(cell: Cell, label: str = "a data") -> date:
    """Data e hora em UTC (exports da Binance) para o dia em Brasília.

    Uma operação às 01:00 UTC de 02/03 aconteceu em 01/03 no horário de Brasília, e é essa
    a data que vale para a PTAX e para o ledger.
    """
    if isinstance(cell, datetime):
        moment = cell
    elif isinstance(cell, date):
        return cell
    else:
        value = required_text(cell, label)
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                moment = datetime.strptime(value, pattern).replace(tzinfo=UTC)
                break
            except ValueError:
                continue
        else:
            raise LineError(f"Data inválida em {label}: {value}.")
    if moment.tzinfo is None:  # célula de data e hora do Excel: o export é em UTC
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(SAO_PAULO).date()


def number(cell: Cell, label: str, decimal: str = ",") -> Decimal:
    value = optional_number(cell, label, decimal)
    if value is None:
        raise LineError(f"Falta {label}.")
    return value


def optional_number(cell: Cell, label: str, decimal: str = ",") -> Decimal | None:
    """Número de uma célula. ``decimal=","`` é o formato brasileiro (1.234,56, que também
    aceita 38.45 sem milhar); ``"."`` é o americano dos exports em inglês (1,234.56)."""
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
        if decimal == ".":
            plain = raw.replace(",", "")
            if not _US_NUMBER.match(plain):
                raise ValueError(raw)
            return to_decimal(plain)
        # "0.001" é decimal com ponto, não milhar: ninguém escreve um como "0.001".
        if _LEADING_ZERO_DOT.match(raw):
            return to_decimal(raw)
        return parse_br_decimal(raw)
    except (ValueError, InvalidOperation) as exc:
        raise LineError(f"Número inválido em {label}: {raw}.") from exc


def amount_and_coin(cell: Cell, label: str) -> tuple[Decimal, str]:
    """ "0.00100000BTC" ou "100 USDT" (formato da Binance) em quantidade e moeda."""
    value = required_text(cell, label).replace(" ", " ")  # espaço sem quebra do Excel
    match = _AMOUNT_COIN.match(value.strip())
    if match is None:
        raise LineError(f"Valor com moeda inválido em {label}: {value}.")
    return number(match.group(1), label, "."), match.group(2)
