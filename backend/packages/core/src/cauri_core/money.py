"""Dinheiro e quantidades sempre em Decimal. Float nunca entra no domínio."""

from __future__ import annotations

import re
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal(0)
ONE = Decimal(1)

_BR_NUMBER = re.compile(r"^-?\d{1,3}(\.\d{3})*(,\d+)?$|^-?\d+(,\d+)?$")


def to_decimal(value: Decimal | int | str) -> Decimal:
    """Converte para Decimal recusando float (que já chega com erro binário)."""
    if isinstance(value, float):
        raise TypeError("float não é aceito para dinheiro; use str ou Decimal")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"número inválido: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"número inválido: {value!r}")
    return result


def parse_br_decimal(text: str) -> Decimal:
    """Lê número no formato brasileiro: ``1.234,56``, ``38,45``, ``100``.

    Também aceita ponto decimal sem separador de milhar (``38.45``), comum em
    exportações de sistemas.
    """
    cleaned = text.strip().replace("R$", "").replace(" ", "").replace(" ", "")
    if not cleaned:
        raise ValueError("número vazio")
    if _BR_NUMBER.match(cleaned):
        return to_decimal(cleaned.replace(".", "").replace(",", "."))
    if re.fullmatch(r"-?\d+\.\d+", cleaned):
        return to_decimal(cleaned)
    raise ValueError(f"número inválido: {text!r}")


def q2(value: Decimal) -> Decimal:
    """Arredonda para centavos (meio para o par, o padrão bancário)."""
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


def trunc(value: Decimal, places: int) -> Decimal:
    """Trunca (sem arredondar) em ``places`` casas decimais."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


def format_brl(value: Decimal) -> str:
    """Formata em reais no padrão pt-BR: ``R$ 1.234,56`` (negativo: ``-R$ 1.234,56``)."""
    rounded = q2(value)
    sign = "-" if rounded < 0 else ""
    integer, _, cents = f"{abs(rounded):.2f}".partition(".")
    groups = []
    while integer:
        groups.append(integer[-3:])
        integer = integer[:-3]
    return f"{sign}R$ {'.'.join(reversed(groups))},{cents}"
