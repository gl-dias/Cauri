"""Formatos conhecidos, na ordem em que o cabeçalho é testado."""

from __future__ import annotations

from collections.abc import Sequence

from cauri_importers.adapters.b3 import B3MovimentacaoAdapter, B3NegociacaoAdapter
from cauri_importers.adapters.generic import GenericAdapter
from cauri_importers.model import Adapter

ADAPTERS: tuple[Adapter, ...] = (B3NegociacaoAdapter(), B3MovimentacaoAdapter(), GenericAdapter())


def batch_warnings(adapter_names: Sequence[str]) -> list[str]:
    """Avisos que dependem do conjunto de arquivos do envio, não de uma linha."""
    names = set(adapter_names)
    out: list[str] = []
    if "b3-movimentacao" in names and "b3-negociacao" not in names:
        out.append(
            "As compras e vendas de ações e FIIs vêm do export de Negociação da B3; a "
            "Movimentação traz proventos, eventos e Tesouro. Se ainda não importou a "
            "Negociação desse período, envie também."
        )
    if "b3-negociacao" in names:
        out.append(
            "O export de Negociação da B3 não traz corretagem nem emolumentos: as compras "
            "entram sem taxas. Dá para editar cada compra depois, se quiser o preço médio "
            "com as taxas."
        )
    return out
