"""Ingestão de dados de mercado. Preço de mercado é compartilhado: não pertence a usuário.

``run_daily``: fechamento do dia (duas passadas). ``run_backfill``: histórico.
``sync_*``: dados de referência (corretoras, ativos, apelidos).
"""

from cauri_ingest_market.backfill import BackfillReport, run_backfill, tracked_assets
from cauri_ingest_market.daily import DailyReport, run_daily
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
    "DailyReport",
    "normalize_alias",
    "run_backfill",
    "run_daily",
    "sync_aliases",
    "sync_b3_assets",
    "sync_brokers",
    "sync_crypto",
    "sync_tesouro_assets",
    "tracked_assets",
]
