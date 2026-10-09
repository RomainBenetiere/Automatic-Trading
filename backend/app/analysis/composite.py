"""Composite scoring module — combines technical, fundamental, and dividend scores."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


# ── Signal thresholds ───────────────────────────────────────────────────

SIGNAL_THRESHOLDS = {
    "strong_buy": 75.0,
    "buy": 62.0,
    "hold_upper": 55.0,
    "hold_lower": 45.0,
    "reduce": 38.0,
    # Below reduce → sell
}


@dataclass
class CompositeResult:
    """Result of composite scoring with full breakdown."""

    technical_score: float
    fundamental_score: float
    dividend_score: float | None
    composite_score: float
    signal: str  # strong_buy / buy / hold / reduce / sell
    weights: dict[str, float] = field(default_factory=dict)
    details: dict = field(default_factory=dict)


def compute_composite(
    technical_score: float,
    fundamental_score: float,
    dividend_score: float | None,
    asset_type: str,
    weight_override: tuple[float, float, float] | None = None,
    is_accumulating: bool = False,
) -> CompositeResult:
    """Compute the composite score and derive an action signal.

    Args:
        technical_score: normalised technical score (0-100)
        fundamental_score: normalised fundamental score (0-100)
        dividend_score: normalised dividend score (0-100) or None
        asset_type: "stock", "etf", "bond", or "crypto"
        weight_override: optional explicit (tech, fund, div) weights (must sum to ~1.0)
        is_accumulating: if True (e.g. accumulating ETF), dividend score is completely
            ignored and its weight is redistributed between technical and fundamental.

    Returns a CompositeResult with the composite score and signal.
    """
    # Get weights
    if weight_override:
        w_tech, w_fund, w_div = weight_override
    else:
        w_tech, w_fund, w_div = settings.get_weights(asset_type)

    # For accumulating ETFs, ignore dividend score completely and redistribute weights
    if is_accumulating or (asset_type == "etf" and dividend_score is None):
        w_div = 0.0
        tech_fund_total = w_tech + w_fund
        if tech_fund_total > 0:
            w_tech = w_tech / tech_fund_total
            w_fund = w_fund / tech_fund_total
        else:
            w_tech = 0.5
            w_fund = 0.5

    # Compute weighted composite
    composite = (
        w_tech * technical_score
        + w_fund * fundamental_score
        + (w_div * (dividend_score or 0.0))
    )

    # Derive signal from composite score
    if composite >= SIGNAL_THRESHOLDS["strong_buy"]:
        signal = "strong_buy"
    elif composite >= SIGNAL_THRESHOLDS["buy"]:
        signal = "buy"
    elif composite >= SIGNAL_THRESHOLDS["hold_lower"]:
        signal = "hold"
    elif composite >= SIGNAL_THRESHOLDS["reduce"]:
        signal = "reduce"
    else:
        signal = "sell"

    weights_dict = {
        "technical": round(w_tech, 3),
        "fundamental": round(w_fund, 3),
        "dividend": round(w_div, 3),
    }

    result = CompositeResult(
        technical_score=round(technical_score, 1),
        fundamental_score=round(fundamental_score, 1),
        dividend_score=round(dividend_score, 1) if dividend_score is not None else None,
        composite_score=round(composite, 1),
        signal=signal,
        weights=weights_dict,
        details={
            "asset_type": asset_type,
            "is_accumulating": is_accumulating,
            "thresholds": SIGNAL_THRESHOLDS,
            "weighted_contributions": {
                "technical": round(w_tech * technical_score, 1),
                "fundamental": round(w_fund * fundamental_score, 1),
                "dividend": round(w_div * (dividend_score or 0.0), 1),
            },
        },
    )

    logger.info(
        "Composite score: %.1f (%s) — tech=%.1f×%.0f%% + fund=%.1f×%.0f%% + div=%s×%.0f%%",
        composite,
        signal,
        technical_score,
        w_tech * 100,
        fundamental_score,
        w_fund * 100,
        f"{dividend_score:.1f}" if dividend_score is not None else "N/A",
        w_div * 100,
    )

    return result


def weights_to_json(weights: dict[str, float]) -> str:
    """Serialise weights dict to JSON for storage."""
    return json.dumps(weights)
