"""Núcleo de cálculo do engine: funções puras, sem banco nem rede."""

from cauri_engine.calc.fixed_income import (
    Accrual,
    CdiCurve,
    FixedIncomeBook,
    RedemptionExceedsBalanceError,
    daily_factor,
)
from cauri_engine.calc.ordering import in_order, sort_key
from cauri_engine.calc.performance import (
    cdi_index,
    daily_return,
    ipca_index,
    next_quota,
    period_return,
)
from cauri_engine.calc.positions import AssetBook, Oversell, OversellError, find_oversell, replay
from cauri_engine.calc.valuation import (
    AssetInfo,
    BucketSnapshot,
    DaySnapshot,
    PortfolioInputs,
    PositionSnapshot,
    PriceBook,
    compute_snapshots,
)

__all__ = [
    "Accrual",
    "AssetBook",
    "AssetInfo",
    "BucketSnapshot",
    "CdiCurve",
    "DaySnapshot",
    "FixedIncomeBook",
    "Oversell",
    "OversellError",
    "PortfolioInputs",
    "PositionSnapshot",
    "PriceBook",
    "RedemptionExceedsBalanceError",
    "cdi_index",
    "compute_snapshots",
    "daily_factor",
    "daily_return",
    "find_oversell",
    "in_order",
    "ipca_index",
    "next_quota",
    "period_return",
    "replay",
    "sort_key",
]
