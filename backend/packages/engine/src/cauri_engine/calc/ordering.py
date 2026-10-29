"""Ordem canônica das movimentações, a mesma usada pelo banco.

Dentro do mesmo dia: eventos corporativos primeiro (valem na data ex), depois
entradas (compra, aporte), depois saídas (venda, resgate), por último proventos.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from cauri_core import CORPORATE_EVENTS, Movement, MovementType

_RANK: dict[MovementType, int] = {
    **dict.fromkeys(CORPORATE_EVENTS, 0),
    MovementType.COMPRA: 1,
    MovementType.APORTE: 1,
    MovementType.VENDA: 2,
    MovementType.RESGATE: 2,
    MovementType.PROVENTO: 3,
}


def sort_key(movement: Movement) -> tuple[date, int, int, str]:
    return (movement.trade_date, _RANK[movement.type], movement.seq, str(movement.id))


def in_order(movements: Iterable[Movement]) -> list[Movement]:
    return sorted(movements, key=sort_key)
