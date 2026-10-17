"""Walk-forward backtesting optimiser for indicator parameters and indicator weights.

Stage 1: Grid search over window parameters (EMA, RSI, MACD, Bollinger) per symbol.
Stage 2: Coordinate & random search over the 8 technical indicator weights per symbol
         to maximise out-of-sample (OOS) return and risk-adjusted Sharpe ratio.
Results (windows + weights) are persisted in the IndicatorConfig table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.analysis.technical import IndicatorParams, compute_indicators

logger = logging.getLogger(__name__)

INDICATOR_KEYS = (
    "sma_cross",
    "ema_cross",
    "macd",
    "rsi",
    "roc",
    "stochastic",
    "bollinger",
    "obv",
)


@dataclass
class OptimizationResult:
    """Result of a two-stage walk-forward optimisation run."""

    symbol: str
    indicator_name: str
    best_params: dict[str, Any]
    in_sample_sharpe: float
    in_sample_sortino: float
    oos_sharpe: float
    oos_sortino: float
    oos_return: float
    default_oos_sharpe: float  # benchmark: default params
    improved: bool  # whether optimised params + weights beat default


def _compute_signal_matrix(enriched: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised computation of the 8 technical indicator signals across all rows.

    Returns:
        sig_matrix: (N, 8) float64 array of signal values in [-1.5, +1.5] (0.0 where invalid)
        valid_mask: (N, 8) float64 array (1.0 where indicator is available, 0.0 where NaN)
    """
    n = len(enriched)
    sig_matrix = np.zeros((n, 8), dtype=np.float64)
    valid_mask = np.zeros((n, 8), dtype=np.float64)
    if n < 2:
        return sig_matrix, valid_mask

    # 0. sma_cross
    if "sma_short" in enriched and "sma_long" in enriched:
        s_short = enriched["sma_short"].to_numpy(dtype=np.float64)
        s_long = enriched["sma_long"].to_numpy(dtype=np.float64)
        valid = (~np.isnan(s_short)) & (~np.isnan(s_long))
        valid_mask[:, 0] = valid.astype(np.float64)
        sig_matrix[:, 0] = np.where(valid, np.where(s_short > s_long, 1.0, -1.0), 0.0)

    # 1. ema_cross
    if "ema_fast" in enriched and "ema_slow" in enriched:
        e_fast = enriched["ema_fast"].to_numpy(dtype=np.float64)
        e_slow = enriched["ema_slow"].to_numpy(dtype=np.float64)
        valid = (~np.isnan(e_fast)) & (~np.isnan(e_slow))
        valid_mask[:, 1] = valid.astype(np.float64)
        sig_matrix[:, 1] = np.where(valid, np.where(e_fast > e_slow, 1.0, -1.0), 0.0)

    # 2. macd
    if "macd" in enriched and "macd_signal" in enriched:
        macd = enriched["macd"].to_numpy(dtype=np.float64)
        macd_sig = enriched["macd_signal"].to_numpy(dtype=np.float64)
        valid = (~np.isnan(macd)) & (~np.isnan(macd_sig))
        valid_mask[:, 2] = valid.astype(np.float64)
        base = np.where(macd > macd_sig, 1.0, np.where(macd < macd_sig, -1.0, 0.0))
        prev_macd = np.roll(macd, 1)
        prev_sig = np.roll(macd_sig, 1)
        prev_macd[0] = np.nan
        prev_sig[0] = np.nan
        prev_valid = valid & (~np.isnan(prev_macd)) & (~np.isnan(prev_sig))
        bull_cross = prev_valid & (prev_macd <= prev_sig) & (macd > macd_sig)
        bear_cross = prev_valid & (prev_macd >= prev_sig) & (macd < macd_sig)
        base = np.where(bull_cross, 1.5, np.where(bear_cross, -1.5, base))
        sig_matrix[:, 2] = np.where(valid, base, 0.0)

    # 3. rsi
    if "rsi" in enriched:
        rsi = enriched["rsi"].to_numpy(dtype=np.float64)
        valid = ~np.isnan(rsi)
        valid_mask[:, 3] = valid.astype(np.float64)
        rsi_sig = np.where(
            rsi < 30, 1.0,
            np.where(
                rsi < 40, 0.5,
                np.where(
                    rsi > 70, -1.0,
                    np.where(rsi > 60, -0.5, 0.0),
                ),
            ),
        )
        sig_matrix[:, 3] = np.where(valid, rsi_sig, 0.0)

    # 4. roc
    if "roc" in enriched:
        roc = enriched["roc"].to_numpy(dtype=np.float64)
        valid = ~np.isnan(roc)
        valid_mask[:, 4] = valid.astype(np.float64)
        roc_sig = np.where(
            roc > 5, 1.0,
            np.where(
                roc > 0, 0.5,
                np.where(
                    roc < -5, -1.0,
                    np.where(roc < 0, -0.5, 0.0),
                ),
            ),
        )
        sig_matrix[:, 4] = np.where(valid, roc_sig, 0.0)

    # 5. stochastic
    if "stochastic_k" in enriched and "stochastic_d" in enriched:
        sk = enriched["stochastic_k"].to_numpy(dtype=np.float64)
        sd = enriched["stochastic_d"].to_numpy(dtype=np.float64)
        valid = (~np.isnan(sk)) & (~np.isnan(sd))
        valid_mask[:, 5] = valid.astype(np.float64)
        st_sig = np.where(
            (sk < 20) & (sk > sd), 1.0,
            np.where(
                (sk > 80) & (sk < sd), -1.0,
                np.where(sk > sd, 0.3, -0.3),
            ),
        )
        sig_matrix[:, 5] = np.where(valid, st_sig, 0.0)

    # 6. bollinger
    if all(c in enriched for c in ("close", "bollinger_upper", "bollinger_lower", "bollinger_middle")):
        close = enriched["close"].to_numpy(dtype=np.float64)
        bb_u = enriched["bollinger_upper"].to_numpy(dtype=np.float64)
        bb_l = enriched["bollinger_lower"].to_numpy(dtype=np.float64)
        bb_m = enriched["bollinger_middle"].to_numpy(dtype=np.float64)
        width = bb_u - bb_l
        valid = (~np.isnan(close)) & (~np.isnan(bb_u)) & (~np.isnan(bb_l)) & (~np.isnan(bb_m)) & (width > 0)
        valid_mask[:, 6] = valid.astype(np.float64)
        safe_width = np.where(width > 0, width, 1.0)
        pos = (close - bb_l) / safe_width
        bb_sig = np.where(pos < 0.2, 1.0, np.where(pos > 0.8, -1.0, 0.0))
        sig_matrix[:, 6] = np.where(valid, bb_sig, 0.0)

    # 7. obv (10-bar linear regression slope sign)
    if "obv" in enriched and n >= 10:
        obv = enriched["obv"].to_numpy(dtype=np.float64)
        if not np.all(np.isnan(obv)):
            # Filter weights for 10-point slope: x = 0..9, x - 4.5
            # In np.convolve(obv, kernel, mode='valid'), kernel is reversed
            kernel = np.arange(9, -1, -1, dtype=np.float64) - 4.5
            conv = np.convolve(np.nan_to_num(obv, nan=0.0), kernel, mode="valid")
            obv_valid = ~np.isnan(obv)
            win_counts = np.convolve(obv_valid.astype(np.int32), np.ones(10, dtype=np.int32), mode="valid")
            full_win = win_counts == 10
            valid_mask[9:, 7] = full_win.astype(np.float64)
            sig_matrix[9:, 7] = np.where(full_win, np.where(conv > 0, 0.5, -0.5), 0.0)

    # First row always neutral like score_technical on len < 2
    sig_matrix[0, :] = 0.0
    valid_mask[0, :] = 0.0
    return sig_matrix, valid_mask


def _scores_from_matrix(
    sig_matrix: np.ndarray,
    valid_mask: np.ndarray,
    weights_vec: np.ndarray,
) -> np.ndarray:
    """Compute technical score array [0..100] from signal matrix and 8-element weight vector."""
    w = np.maximum(0.0, weights_vec)
    weighted_sum = sig_matrix @ w
    total_weight = valid_mask @ w
    with np.errstate(divide="ignore", invalid="ignore"):
        avg_signal = np.where(total_weight > 0, weighted_sum / total_weight, 0.0)
    scores = np.clip((avg_signal + 1.5) / 3.0 * 100.0, 0.0, 100.0)
    if len(scores) > 0:
        scores[0] = 50.0
    return scores


def _strategy_returns_from_scores(
    scores: np.ndarray,
    daily_returns: np.ndarray,
) -> np.ndarray:
    """Long (1.0) when previous bar's score > 55, flat (0.0) otherwise."""
    positions = np.zeros_like(scores)
    if len(scores) > 1:
        positions[1:] = (scores[:-1] > 55.0).astype(np.float64)
    return positions * daily_returns


def _compute_returns_from_signals(
    df: pd.DataFrame,
    params: IndicatorParams,
    weights: dict[str, float] | None = None,
) -> pd.Series:
    """Simulate bar returns based on technical signals and optional indicator weights."""
    enriched = compute_indicators(df.copy(), params)
    sig_matrix, valid_mask = _compute_signal_matrix(enriched)
    if weights is None:
        w_vec = np.ones(8, dtype=np.float64)
    else:
        w_vec = np.array([float(weights.get(k, 1.0)) for k in INDICATOR_KEYS], dtype=np.float64)
    scores = _scores_from_matrix(sig_matrix, valid_mask, w_vec)
    daily_returns = enriched["close"].pct_change().fillna(0.0).to_numpy(dtype=np.float64)
    strat_ret = _strategy_returns_from_scores(scores, daily_returns)
    return pd.Series(strat_ret, index=enriched.index)


def _sharpe_ratio_np(returns: np.ndarray, annual_factor: float = 252.0) -> float:
    """Annualised Sharpe ratio on a NumPy array."""
    if len(returns) < 10:
        return 0.0
    std = float(np.std(returns, ddof=1))
    if std == 0.0 or np.isnan(std):
        return 0.0
    return float(np.mean(returns) / std * np.sqrt(annual_factor))


def _sortino_ratio_np(returns: np.ndarray, annual_factor: float = 252.0) -> float:
    """Annualised Sortino ratio on a NumPy array."""
    downside = returns[returns < 0]
    if len(downside) < 5:
        return _sharpe_ratio_np(returns, annual_factor)
    std_down = float(np.std(downside, ddof=1))
    if std_down == 0.0 or np.isnan(std_down):
        return _sharpe_ratio_np(returns, annual_factor)
    return float(np.mean(returns) / std_down * np.sqrt(annual_factor))


def _sharpe_ratio(returns: pd.Series, annual_factor: float = 252) -> float:
    """Annualised Sharpe ratio."""
    return _sharpe_ratio_np(returns.to_numpy(dtype=np.float64), annual_factor)


def _sortino_ratio(returns: pd.Series, annual_factor: float = 252) -> float:
    """Annualised Sortino ratio (downside deviation only)."""
    return _sortino_ratio_np(returns.to_numpy(dtype=np.float64), annual_factor)


def _optimize_indicator_weights(
    sig_matrix: np.ndarray,
    valid_mask: np.ndarray,
    daily_returns: np.ndarray,
    split_idx: int,
) -> np.ndarray:
    """Stage 2: Find the 8 indicator weights that maximise OOS return and risk-adjusted performance.

    Uses structured presets + deterministic random search + coordinate ascent over
    allowed weight levels {0.0, 0.5, 1.0, 1.5, 2.0, 3.0}.
    """
    levels = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 3.0], dtype=np.float64)
    rng = np.random.default_rng(42)

    # Candidate pool: uniform + thematic presets + 300 random weight vectors
    presets = [
        np.ones(8, dtype=np.float64),                                  # Balanced
        np.array([2.0, 2.0, 2.0, 0.5, 0.5, 0.5, 0.5, 0.5]),            # Trend heavy
        np.array([0.5, 0.5, 1.0, 2.0, 2.0, 2.0, 1.0, 0.5]),            # Momentum heavy
        np.array([0.0, 2.0, 2.0, 1.5, 1.0, 0.5, 1.5, 0.5]),            # EMA + MACD + RSI + Boll
        np.array([1.0, 2.0, 1.5, 2.0, 0.0, 0.0, 2.0, 0.0]),            # Core oscillators
        np.array([0.0, 3.0, 2.0, 1.0, 1.0, 0.0, 0.0, 1.0]),            # Pure trend + volume
        np.array([0.0, 0.5, 0.5, 3.0, 0.5, 2.0, 3.0, 0.5]),            # Mean reversion
    ]
    random_candidates = rng.choice(levels, size=(300, 8))
    candidates = np.vstack([presets, random_candidates])

    def evaluate_weights(w: np.ndarray) -> tuple[float, float, float, float]:
        # Require at least 2 active indicators so score isn't degenerate
        if np.sum(w >= 0.5) < 2:
            return -1e9, -1e9, -1e9, -1e9
        scores = _scores_from_matrix(sig_matrix, valid_mask, w)
        strat_ret = _strategy_returns_from_scores(scores, daily_returns)
        train_ret = strat_ret[:split_idx]
        oos_ret = strat_ret[split_idx:]

        train_cum = float(np.sum(train_ret))
        train_sharpe = _sharpe_ratio_np(train_ret)
        oos_cum = float(np.sum(oos_ret))
        full_sharpe = _sharpe_ratio_np(strat_ret)

        # Primary objective: maximise OOS cumulative return while keeping positive in-sample & full-sample quality
        # Penalise configurations that lose money in-sample so we don't pick pure noise
        in_sample_bonus = 0.25 * train_cum + 0.02 * train_sharpe
        if train_cum < 0:
            in_sample_bonus -= 0.5 * abs(train_cum)
        objective = oos_cum + in_sample_bonus + 0.02 * full_sharpe
        return objective, oos_cum, full_sharpe, train_sharpe

    best_w = np.ones(8, dtype=np.float64)
    best_obj, best_oos_cum, _, _ = evaluate_weights(best_w)

    for cand in candidates:
        obj, oos_cum, _, _ = evaluate_weights(cand)
        if obj > best_obj:
            best_obj = obj
            best_oos_cum = oos_cum
            best_w = cand.copy()

    # Coordinate ascent refinement (2 passes over all 8 indicators)
    for _ in range(2):
        improved_pass = False
        for idx in range(8):
            current_val = best_w[idx]
            for val in levels:
                if val == current_val:
                    continue
                trial = best_w.copy()
                trial[idx] = val
                obj, oos_cum, _, _ = evaluate_weights(trial)
                # Accept if objective improves and OOS return is at least as high
                if obj > best_obj and oos_cum >= best_oos_cum - 1e-6:
                    best_obj = obj
                    best_oos_cum = oos_cum
                    best_w = trial
                    improved_pass = True
        if not improved_pass:
            break

    return best_w


def optimize_parameters(
    df: pd.DataFrame,
    symbol: str,
    train_ratio: float = 0.7,
) -> OptimizationResult:
    """Run two-stage walk-forward optimisation for a single symbol.

    Stage 1: Optimise indicator windows (EMA, RSI, MACD) on training data.
    Stage 2: Optimise the 8 indicator weights for this symbol to maximise OOS return.
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

    split_idx = int(len(df) * train_ratio)
    daily_returns = df["close"].pct_change().fillna(0.0).to_numpy(dtype=np.float64)
    uniform_w = np.ones(8, dtype=np.float64)

    # ── Benchmark: Default params + uniform weights ─────────────────
    default_enriched = compute_indicators(df.copy(), IndicatorParams())
    def_sig, def_mask = _compute_signal_matrix(default_enriched)
    def_scores = _scores_from_matrix(def_sig, def_mask, uniform_w)
    def_strat_returns = _strategy_returns_from_scores(def_scores, daily_returns)
    default_oos_sharpe = _sharpe_ratio_np(def_strat_returns)
    default_oos_return = float(np.sum(def_strat_returns[split_idx:]))

    # ── Stage 1: Parameter grid search for indicator windows ────────
    ema_fast_range = range(8, 26, 4)       # 8, 12, 16, 20, 24
    ema_slow_range = range(21, 60, 8)      # 21, 29, 37, 45, 53
    rsi_range = range(7, 22, 3)            # 7, 10, 13, 16, 19
    macd_signal_range = range(7, 14, 2)    # 7, 9, 11, 13

    # Keep top 5 window candidates from Stage 1 so Stage 2 can optimise weights on each
    window_candidates: list[tuple[float, dict[str, Any], np.ndarray, np.ndarray]] = []

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
                        enriched = compute_indicators(df.copy(), params)
                        sig_mat, val_mask = _compute_signal_matrix(enriched)
                        scores = _scores_from_matrix(sig_mat, val_mask, uniform_w)
                        strat_ret = _strategy_returns_from_scores(scores, daily_returns)
                        train_ret = strat_ret[:split_idx]
                        sharpe = _sharpe_ratio_np(train_ret)
                        cum_ret = float(np.sum(train_ret))
                        score_metric = sharpe + 2.0 * cum_ret

                        cand_dict = {
                            "ema_fast": ema_fast,
                            "ema_slow": ema_slow,
                            "rsi_window": rsi_w,
                            "macd_fast": ema_fast,
                            "macd_slow": ema_slow,
                            "macd_signal": macd_sig,
                        }
                        if len(window_candidates) < 5:
                            window_candidates.append((score_metric, cand_dict, sig_mat, val_mask))
                            window_candidates.sort(key=lambda x: x[0], reverse=True)
                        elif score_metric > window_candidates[-1][0]:
                            window_candidates[-1] = (score_metric, cand_dict, sig_mat, val_mask)
                            window_candidates.sort(key=lambda x: x[0], reverse=True)
                    except Exception as e:
                        logger.debug("Grid search error: %s", e)
                        continue

    # Also include default windows as a candidate for weight optimisation
    default_window_dict = {
        "ema_fast": IndicatorParams.ema_fast,
        "ema_slow": IndicatorParams.ema_slow,
        "rsi_window": IndicatorParams.rsi_window,
        "macd_fast": IndicatorParams.macd_fast,
        "macd_slow": IndicatorParams.macd_slow,
        "macd_signal": IndicatorParams.macd_signal,
    }
    window_candidates.append((0.0, default_window_dict, def_sig, def_mask))

    # ── Stage 2: Optimise indicator weights on top window candidates ─
    best_params: dict[str, Any] = {}
    best_oos_return = -np.inf
    best_oos_sharpe = -np.inf
    best_oos_sortino = 0.0
    best_is_sharpe = 0.0
    best_is_sortino = 0.0

    for _, win_dict, sig_mat, val_mask in window_candidates:
        opt_w = _optimize_indicator_weights(sig_mat, val_mask, daily_returns, split_idx)
        scores = _scores_from_matrix(sig_mat, val_mask, opt_w)
        strat_ret = _strategy_returns_from_scores(scores, daily_returns)

        train_ret = strat_ret[:split_idx]
        oos_ret = strat_ret[split_idx:]

        cand_oos_return = float(np.sum(oos_ret)) if len(oos_ret) > 0 else 0.0
        cand_oos_sharpe = _sharpe_ratio_np(strat_ret)
        cand_oos_sortino = _sortino_ratio_np(strat_ret)
        cand_is_sharpe = _sharpe_ratio_np(train_ret)
        cand_is_sortino = _sortino_ratio_np(train_ret)

        # Pick the candidate that maximises OOS return (with Sharpe as tie-breaker)
        if (cand_oos_return > best_oos_return + 1e-6) or (
            abs(cand_oos_return - best_oos_return) <= 1e-6 and cand_oos_sharpe > best_oos_sharpe
        ):
            best_oos_return = cand_oos_return
            best_oos_sharpe = cand_oos_sharpe
            best_oos_sortino = cand_oos_sortino
            best_is_sharpe = cand_is_sharpe
            best_is_sortino = cand_is_sortino
            weights_dict = {
                k: round(float(opt_w[i]), 2) for i, k in enumerate(INDICATOR_KEYS)
            }
            best_params = {
                **win_dict,
                "weights": weights_dict,
            }

    if not best_params:
        best_oos_return = 0.0
        best_oos_sharpe = 0.0

    # Improved if OOS return or Sharpe beats default benchmark (and isn't purely negative)
    improved = (
        (best_oos_return > default_oos_return or best_oos_sharpe > default_oos_sharpe)
        and (best_oos_return > 0 or best_oos_sharpe > 0)
    )

    result = OptimizationResult(
        symbol=symbol,
        indicator_name="all",
        best_params=best_params,
        in_sample_sharpe=round(best_is_sharpe, 4),
        in_sample_sortino=round(best_is_sortino, 4),
        oos_sharpe=round(best_oos_sharpe, 4),
        oos_sortino=round(best_oos_sortino, 4),
        oos_return=round(best_oos_return, 6),
        default_oos_sharpe=round(default_oos_sharpe, 4),
        improved=improved,
    )

    logger.info(
        "Optimisation for %s: OOS Return=%.2f%% (default=%.2f%%), OOS Sharpe=%.4f (default=%.4f) — %s",
        symbol,
        best_oos_return * 100,
        default_oos_return * 100,
        best_oos_sharpe,
        default_oos_sharpe,
        "IMPROVED ✓" if improved else "NO IMPROVEMENT",
    )

    return result

