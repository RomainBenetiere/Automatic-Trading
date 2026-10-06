"""Technical analysis module — indicator computation and scoring.

Implements volatility-adaptive parameter selection (§4.1) with optional
walk-forward optimised overrides from the IndicatorConfig table.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import ta

logger = logging.getLogger(__name__)


# ── Volatility regime thresholds ────────────────────────────────────────

@dataclass
class IndicatorParams:
    """Adaptive indicator parameters based on volatility regime."""

    ema_fast: int = 12
    ema_slow: int = 26
    sma_short: int = 20
    sma_long: int = 50
    rsi_window: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bollinger_window: int = 20
    bollinger_std: float = 2.0
    atr_window: int = 14
    stochastic_window: int = 14
    roc_window: int = 12


# Default parameter sets per volatility regime
PARAMS_HIGH_VOLATILITY = IndicatorParams(
    ema_fast=8, ema_slow=21, sma_short=10, sma_long=30,
    rsi_window=9, macd_fast=8, macd_slow=21, macd_signal=7,
    bollinger_window=15, atr_window=10, stochastic_window=9, roc_window=8,
)

PARAMS_MEDIUM_VOLATILITY = IndicatorParams(
    ema_fast=12, ema_slow=26, sma_short=20, sma_long=50,
    rsi_window=14, macd_fast=12, macd_slow=26, macd_signal=9,
    bollinger_window=20, atr_window=14, stochastic_window=14, roc_window=12,
)

PARAMS_LOW_VOLATILITY = IndicatorParams(
    ema_fast=21, ema_slow=55, sma_short=50, sma_long=100,
    rsi_window=21, macd_fast=21, macd_slow=55, macd_signal=12,
    bollinger_window=30, bollinger_std=2.5, atr_window=21,
    stochastic_window=21, roc_window=20,
)


def classify_volatility(df: pd.DataFrame, window: int = 30) -> str:
    """Classify asset volatility regime based on ATR relative to price.

    Returns 'high', 'medium', or 'low'.
    """
    if len(df) < window + 1:
        return "medium"

    atr = ta.volatility.AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=window
    ).average_true_range()

    # ATR as percentage of price
    atr_pct = (atr / df["close"]).dropna()
    if len(atr_pct) == 0:
        return "medium"

    avg_atr_pct = atr_pct.iloc[-window:].mean()

    if avg_atr_pct > 0.04:  # > 4% daily range → high volatility
        return "high"
    elif avg_atr_pct < 0.015:  # < 1.5% daily range → low volatility
        return "low"
    return "medium"


def get_params(
    volatility_regime: str,
    db_overrides: dict[str, Any] | None = None,
) -> IndicatorParams:
    """Get indicator parameters for a volatility regime, with optional DB overrides."""
    base = {
        "high": PARAMS_HIGH_VOLATILITY,
        "low": PARAMS_LOW_VOLATILITY,
    }.get(volatility_regime, PARAMS_MEDIUM_VOLATILITY)

    if db_overrides:
        # Apply per-field overrides from IndicatorConfig
        params_dict = {
            k: db_overrides.get(k, getattr(base, k))
            for k in base.__dataclass_fields__
        }
        return IndicatorParams(**params_dict)

    return base


# ── Indicator computation ───────────────────────────────────────────────

def compute_indicators(
    df: pd.DataFrame,
    params: IndicatorParams | None = None,
) -> pd.DataFrame:
    """Compute all technical indicators on a price DataFrame.

    Args:
        df: DataFrame with columns: open, high, low, close, volume (indexed by date)
        params: indicator parameters (auto-detected if None)

    Returns the DataFrame enriched with indicator columns.
    """
    if len(df) < 5:
        logger.warning("Not enough data to compute indicators (%d rows)", len(df))
        return df

    if params is None:
        regime = classify_volatility(df)
        params = get_params(regime)
        logger.info("Auto-detected volatility regime: %s", regime)

    df = df.copy()

    # ── Trend ──────────────────────────────────────────────────────
    df["sma_short"] = ta.trend.SMAIndicator(
        close=df["close"], window=params.sma_short
    ).sma_indicator()

    df["sma_long"] = ta.trend.SMAIndicator(
        close=df["close"], window=params.sma_long
    ).sma_indicator()

    df["ema_fast"] = ta.trend.EMAIndicator(
        close=df["close"], window=params.ema_fast
    ).ema_indicator()

    df["ema_slow"] = ta.trend.EMAIndicator(
        close=df["close"], window=params.ema_slow
    ).ema_indicator()

    macd_ind = ta.trend.MACD(
        close=df["close"],
        window_fast=params.macd_fast,
        window_slow=params.macd_slow,
        window_sign=params.macd_signal,
    )
    df["macd"] = macd_ind.macd()
    df["macd_signal"] = macd_ind.macd_signal()
    df["macd_histogram"] = macd_ind.macd_diff()

    # ── Momentum ───────────────────────────────────────────────────
    df["rsi"] = ta.momentum.RSIIndicator(
        close=df["close"], window=params.rsi_window
    ).rsi()

    df["roc"] = ta.momentum.ROCIndicator(
        close=df["close"], window=params.roc_window
    ).roc()

    stoch = ta.momentum.StochasticOscillator(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=params.stochastic_window,
        smooth_window=3,
    )
    df["stochastic_k"] = stoch.stoch()
    df["stochastic_d"] = stoch.stoch_signal()

    # ── Volatility ─────────────────────────────────────────────────
    bollinger = ta.volatility.BollingerBands(
        close=df["close"],
        window=params.bollinger_window,
        window_dev=params.bollinger_std,
    )
    df["bollinger_upper"] = bollinger.bollinger_hband()
    df["bollinger_middle"] = bollinger.bollinger_mavg()
    df["bollinger_lower"] = bollinger.bollinger_lband()

    df["atr"] = ta.volatility.AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=params.atr_window,
    ).average_true_range()

    # ── Volume ─────────────────────────────────────────────────────
    if "volume" in df.columns and df["volume"].sum() > 0:
        df["obv"] = ta.volume.OnBalanceVolumeIndicator(
            close=df["close"], volume=df["volume"]
        ).on_balance_volume()

        try:
            df["vwap"] = ta.volume.VolumeWeightedAveragePrice(
                high=df["high"],
                low=df["low"],
                close=df["close"],
                volume=df["volume"],
            ).volume_weighted_average_price()
        except Exception:
            df["vwap"] = np.nan
    else:
        df["obv"] = np.nan
        df["vwap"] = np.nan

    return df


# ── Scoring ─────────────────────────────────────────────────────────────

@dataclass
class TechnicalSignals:
    """Individual technical signals contributing to the final score."""

    trend_sma_cross: float = 0.0       # +1 bullish, -1 bearish
    trend_ema_cross: float = 0.0
    trend_macd: float = 0.0
    momentum_rsi: float = 0.0
    momentum_roc: float = 0.0
    momentum_stochastic: float = 0.0
    volatility_bollinger: float = 0.0
    volume_obv_trend: float = 0.0
    signals: dict = field(default_factory=dict)


def score_technical(df: pd.DataFrame) -> tuple[float, TechnicalSignals]:
    """Compute a normalised technical score (0–100) from the latest indicator values.

    Returns (score, signals_detail).
    """
    if len(df) < 2:
        return 50.0, TechnicalSignals()

    latest = df.iloc[-1]
    prev = df.iloc[-2]
    signals = TechnicalSignals()

    signal_values: list[float] = []

    # ── Trend: SMA cross ───────────────────────────────────────────
    if pd.notna(latest.get("sma_short")) and pd.notna(latest.get("sma_long")):
        if latest["sma_short"] > latest["sma_long"]:
            signals.trend_sma_cross = 1.0
        else:
            signals.trend_sma_cross = -1.0
        signal_values.append(signals.trend_sma_cross)

    # ── Trend: EMA cross ───────────────────────────────────────────
    if pd.notna(latest.get("ema_fast")) and pd.notna(latest.get("ema_slow")):
        if latest["ema_fast"] > latest["ema_slow"]:
            signals.trend_ema_cross = 1.0
        else:
            signals.trend_ema_cross = -1.0
        signal_values.append(signals.trend_ema_cross)

    # ── Trend: MACD ────────────────────────────────────────────────
    if pd.notna(latest.get("macd")) and pd.notna(latest.get("macd_signal")):
        if latest["macd"] > latest["macd_signal"]:
            signals.trend_macd = 1.0
        elif latest["macd"] < latest["macd_signal"]:
            signals.trend_macd = -1.0
        # Bonus for crossing
        if pd.notna(prev.get("macd")) and pd.notna(prev.get("macd_signal")):
            if prev["macd"] <= prev["macd_signal"] and latest["macd"] > latest["macd_signal"]:
                signals.trend_macd = 1.5  # Bullish crossover bonus
            elif prev["macd"] >= prev["macd_signal"] and latest["macd"] < latest["macd_signal"]:
                signals.trend_macd = -1.5  # Bearish crossover penalty
        signal_values.append(signals.trend_macd)

    # ── Momentum: RSI ──────────────────────────────────────────────
    rsi = latest.get("rsi")
    if pd.notna(rsi):
        if rsi < 30:
            signals.momentum_rsi = 1.0  # Oversold → bullish
        elif rsi < 40:
            signals.momentum_rsi = 0.5
        elif rsi > 70:
            signals.momentum_rsi = -1.0  # Overbought → bearish
        elif rsi > 60:
            signals.momentum_rsi = -0.5
        else:
            signals.momentum_rsi = 0.0
        signal_values.append(signals.momentum_rsi)

    # ── Momentum: ROC ──────────────────────────────────────────────
    roc = latest.get("roc")
    if pd.notna(roc):
        if roc > 5:
            signals.momentum_roc = 1.0
        elif roc > 0:
            signals.momentum_roc = 0.5
        elif roc < -5:
            signals.momentum_roc = -1.0
        elif roc < 0:
            signals.momentum_roc = -0.5
        signal_values.append(signals.momentum_roc)

    # ── Momentum: Stochastic ───────────────────────────────────────
    stoch_k = latest.get("stochastic_k")
    stoch_d = latest.get("stochastic_d")
    if pd.notna(stoch_k) and pd.notna(stoch_d):
        if stoch_k < 20 and stoch_k > stoch_d:
            signals.momentum_stochastic = 1.0  # Oversold + bullish cross
        elif stoch_k > 80 and stoch_k < stoch_d:
            signals.momentum_stochastic = -1.0  # Overbought + bearish cross
        elif stoch_k > stoch_d:
            signals.momentum_stochastic = 0.3
        else:
            signals.momentum_stochastic = -0.3
        signal_values.append(signals.momentum_stochastic)

    # ── Volatility: Bollinger position ─────────────────────────────
    close = latest.get("close")
    bb_upper = latest.get("bollinger_upper")
    bb_lower = latest.get("bollinger_lower")
    bb_middle = latest.get("bollinger_middle")
    if all(pd.notna(v) for v in [close, bb_upper, bb_lower, bb_middle]):
        bb_width = bb_upper - bb_lower
        if bb_width > 0:
            bb_position = (close - bb_lower) / bb_width  # 0 = at lower, 1 = at upper
            if bb_position < 0.2:
                signals.volatility_bollinger = 1.0  # Near lower band → bullish
            elif bb_position > 0.8:
                signals.volatility_bollinger = -1.0  # Near upper band → bearish
            else:
                signals.volatility_bollinger = 0.0
            signal_values.append(signals.volatility_bollinger)

    # ── Volume: OBV trend ──────────────────────────────────────────
    if len(df) >= 10 and pd.notna(latest.get("obv")):
        obv_series = df["obv"].dropna().iloc[-10:]
        if len(obv_series) >= 5:
            obv_slope = np.polyfit(range(len(obv_series)), obv_series.values, 1)[0]
            if obv_slope > 0:
                signals.volume_obv_trend = 0.5  # Rising volume confirms trend
            else:
                signals.volume_obv_trend = -0.5
            signal_values.append(signals.volume_obv_trend)

    # ── Aggregate score ────────────────────────────────────────────
    if not signal_values:
        return 50.0, signals

    # Average of all signals (range: roughly -1.5 to +1.5)
    avg_signal = np.mean(signal_values)

    # Map from [-1.5, +1.5] to [0, 100]
    score = max(0.0, min(100.0, (avg_signal + 1.5) / 3.0 * 100.0))

    signals.signals = {
        "sma_cross": signals.trend_sma_cross,
        "ema_cross": signals.trend_ema_cross,
        "macd": signals.trend_macd,
        "rsi": signals.momentum_rsi,
        "roc": signals.momentum_roc,
        "stochastic": signals.momentum_stochastic,
        "bollinger": signals.volatility_bollinger,
        "obv_trend": signals.volume_obv_trend,
        "avg_signal": float(avg_signal),
    }

    return round(score, 1), signals
