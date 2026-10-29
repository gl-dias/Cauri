"""Formatos conhecidos, na ordem em que o cabeçalho é testado."""

from __future__ import annotations

from collections.abc import Sequence

from cauri_importers.adapters.b3 import B3MovimentacaoAdapter, B3NegociacaoAdapter
from cauri_importers.adapters.binance import (
    BinanceConvertAdapter,
    BinanceP2PAdapter,
    BinanceSpotAdapter,
    BinanceSpotLegacyAdapter,
    BinanceStatementAdapter,
    BinanceTransfersAdapter,
)
from cauri_importers.adapters.crypto import CryptoTemplateAdapter
from cauri_importers.adapters.generic import GenericAdapter
from cauri_importers.adapters.mapped import MappedAdapter
from cauri_importers.model import Adapter
from cauri_ledger import ImportProfile

ADAPTERS: tuple[Adapter, ...] = (
    B3NegociacaoAdapter(),
    B3MovimentacaoAdapter(),
    BinanceSpotAdapter(),
    BinanceSpotLegacyAdapter(),
    BinanceConvertAdapter(),
    BinanceP2PAdapter(),
    BinanceTransfersAdapter(),
    BinanceStatementAdapter(),
    GenericAdapter(),
    CryptoTemplateAdapter(),
)


def adapters_for(profiles: Sequence[ImportProfile]) -> tuple[Adapter, ...]:
    """Os formatos conhecidos e os perfis que o usuário salvou."""
    return (*ADAPTERS, *(MappedAdapter(p) for p in profiles))


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
    if "binance-extrato" in names and not names & {"binance-trades", "binance-trades-antigo"}:
        out.append(
            "As compras e vendas da Binance vêm do histórico de trades (Spot) e do Convert; "
            "o extrato traz as recompensas de Earn. Se ainda não importou os trades desse "
            "período, envie também."
        )
    if "b3-negociacao" in names:
        out.append(
            "O export de Negociação da B3 não traz corretagem nem emolumentos: as compras "
            "entram sem taxas. Dá para editar cada compra depois, se quiser o preço médio "
            "com as taxas."
        )
    return out
