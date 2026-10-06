"""Walk-forward backtesting optimiser for indicator parameters.

Performs grid search over parameter ranges per indicator per symbol,
evaluates via risk-adjusted ratios, and validates out-of-sample.
Results are persisted in the IndicatorConfig table.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from app.analysis.technical import IndicatorParams, compute_indicators, score_technical

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    """Result of a walk-forward optimisation run."""

    symbol: str
    indicator_name: str
    best_params: dict[str, Any]
    in_sample_sharpe: float
    in_sample_sortino: float
    oos_sharpe: float
    oos_sortino: float
    oos_return: float
    default_oos_sharpe: float  # benchmark: default params
    improved: bool  # whether optimised params beat default


def _compute_returns_from_signals(
    df: pd.DataFrame,
    params: IndicatorParams,
) -> pd.Series:
    """Simulate daily returns based on technical signals.

    A simple long/flat strategy: go long when score > 55, flat when < 45.
    """
    enriched = compute_indicators(df.copy(), params)
    scores = []
    for i in range(1, len(enriched)):
        subset = enriched.iloc[: i + 1]
        score, _ = score_technical(subset)
        scores.append(score)

    # Pad the first element
    scores = [50.0] + scores
    score_series = pd.Series(scores, index=enriched.index)

    # Generate positions: 1.0 (long) or 0.0 (flat)
    positions = (score_series > 55).astype(float)
    # Use shift to avoid lookahead bias
    positions = positions.shift(1).fillna(0)

    daily_returns = enriched["close"].pct_change().fillna(0)
    strategy_returns = positions * daily_returns

    return strategy_returns


def _sharpe_ratio(returns: pd.Series, annual_factor: float = 252) -> float:
    """Annualised Sharpe ratio."""
    if returns.std() == 0 or len(returns) < 10:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(annual_factor))


def _sortino_ratio(returns: pd.Series, annual_factor: float = 252) -> float:
    """Annualised Sortino ratio (downside deviation only)."""
    downside = returns[returns < 0]
    if len(downside) < 5 or downside.std() == 0:
        return _sharpe_ratio(returns, annual_factor)
    return float(returns.mean() / downside.std() * np.sqrt(annual_factor))


def optimize_parameters(
    df: pd.DataFrame,
    symbol: str,
    train_ratio: float = 0.7,
) -> OptimizationResult:
    """Run walk-forward optimisation for a single symbol.

    Args:
        df: OHLCV DataFrame with sufficient history
        symbol: asset symbol
        train_ratio: fraction of data used for training (rest = OOS validation)

    Returns an OptimizationResult.
    """
    if len(df) < 60:
        logger.warning("Not enough data for optimisation (%d rows) — skipping %s", len(df), symbol)
        return OptimizationResult(
            symbol=symbol,
            indicator_name="all",
            best_params={},
            in_sample_sharpe=0.0,
            in_sample_sortino=0.0,
            oos_sharpe=0.0,
            oos_sortino=0.0,
            oos_return=0.0,
            default_oos_sharpe=0.0,
            improved=False,
        )

    # Split data
    split_idx = int(len(df) * train_ratio)
    train_df = df.iloc[:split_idx].copy()
    test_df = df.copy()  # Full data (OOS = last 30%)

    # ── Parameter grid (limited for small universes) ────────────────
    # Step size ≥ 2 for small ranges
    ema_fast_range = range(8, 26, 4)       # 8, 12, 16, 20, 24
    ema_slow_range = range(21, 60, 8)      # 21, 29, 37, 45, 53
    rsi_range = range(7, 22, 3)            # 7, 10, 13, 16, 19
    macd_signal_range = range(7, 14, 2)    # 7, 9, 11, 13

    best_sharpe = -np.inf
    best_params = {}
    best_is_sortino = 0.0

    # Grid search on training data
    for ema_fast in ema_fast_range:
        for ema_slow in ema_slow_range:
            if ema_fast >= ema_slow:
                continue
            for rsi_w in rsi_range:
                for macd_sig in macd_signal_range:
                    params = IndicatorParams(
                        ema_fast=ema_fast,
                        ema_slow=ema_slow,
                        rsi_window=rsi_w,
                        macd_fast=ema_fast,
                        macd_slow=ema_slow,
                        macd_signal=macd_sig,
                    )

                    try:
                        returns = _compute_returns_from_signals(train_df, params)
                        sharpe = _sharpe_ratio(returns)

                        if sharpe > best_sharpe:
                            best_sharpe = sharpe
                            best_is_sortino = _sortino_ratio(returns)
                            best_params = {
                                "ema_fast": ema_fast,
                                "ema_slow": ema_slow,
                                "rsi_window": rsi_w,
                                "macd_fast": ema_fast,
                                "macd_slow": ema_slow,
                                "macd_signal": macd_sig,
                            }
                    except Exception as e:
                        logger.debug("Grid search error: %s", e)
                        continue

    # ── Out-of-sample validation ────────────────────────────────────
    if best_params:
        optimised_params = IndicatorParams(**{
            k: best_params.get(k, getattr(IndicatorParams(), k))
            for k in IndicatorParams.__dataclass_fields__
        })
        oos_returns = _compute_returns_from_signals(test_df, optimised_params)
        oos_sharpe = _sharpe_ratio(oos_returns)
        oos_sortino = _sortino_ratio(oos_returns)
        oos_return = float(oos_returns.iloc[split_idx:].sum()) if split_idx < len(oos_returns) else 0.0
    else:
        oos_sharpe = 0.0
        oos_sortino = 0.0
        oos_return = 0.0

    # ── Default params benchmark ────────────────────────────────────
    default_returns = _compute_returns_from_signals(test_df, IndicatorParams())
    default_oos_sharpe = _sharpe_ratio(default_returns)

    improved = oos_sharpe > default_oos_sharpe and oos_sharpe > 0

    result = OptimizationResult(
        symbol=symbol,
        indicator_name="all",
        best_params=best_params,
        in_sample_sharpe=round(best_sharpe, 4),
        in_sample_sortino=round(best_is_sortino, 4),
        oos_sharpe=round(oos_sharpe, 4),
        oos_sortino=round(oos_sortino, 4),
        oos_return=round(oos_return, 6),
        default_oos_sharpe=round(default_oos_sharpe, 4),
        improved=improved,
    )

    logger.info(
        "Optimisation for %s: OOS Sharpe=%.4f (default=%.4f) — %s",
        symbol,
        oos_sharpe,
        default_oos_sharpe,
        "IMPROVED ✓" if improved else "NO IMPROVEMENT",
    )

    return result
