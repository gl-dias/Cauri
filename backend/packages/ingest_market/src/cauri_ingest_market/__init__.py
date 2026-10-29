"""Ingestão de dados de mercado. Preço de mercado é compartilhado: não pertence a usuário.

Fase 1: histórico (backfill) e dados de referência. O job diário com a brapi entra na
Fase 2.
"""

from cauri_ingest_market.backfill import BackfillReport, run_backfill, tracked_assets
from cauri_ingest_market.reference import (
    normalize_alias,
    sync_aliases,
    sync_b3_assets,
    sync_brokers,
    sync_crypto,
    sync_tesouro_assets,
)

__all__ = [
    "BackfillReport",
    "normalize_alias",
    "run_backfill",
    "sync_aliases",
    "sync_b3_assets",
    "sync_brokers",
    "sync_crypto",
    "sync_tesouro_assets",
    "tracked_assets",
]
