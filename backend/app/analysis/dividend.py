"""Dividend analysis module — yield, regularity, sustainability, and growth scoring."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DividendBreakdown:
    """Breakdown of the dividend score components."""

    yield_score: float = 50.0
    regularity_score: float = 50.0
    payout_ratio_score: float = 50.0
    growth_score: float = 50.0
    details: dict = field(default_factory=dict)


def _score_yield(dividend_yield: float | None) -> float:
    """Score dividend yield — higher is better, but cap to avoid value traps."""
    if dividend_yield is None or dividend_yield <= 0:
        return 20.0  # No dividend
    if dividend_yield > 10:
        return 50.0  # Suspiciously high — potential value trap / cut risk
    if dividend_yield > 6:
        return 75.0
    if dividend_yield > 4:
        return 85.0
    if dividend_yield > 2.5:
        return 75.0
    if dividend_yield > 1.5:
        return 60.0
    return 40.0  # Very low yield


def _score_regularity(
    dividend_history: list[dict[str, Any]],
    lookback_years: int = 5,
) -> float:
    """Score dividend payment regularity over the lookback period.

    Penalizes missed payments and erratic schedules.
    """
    if not dividend_history:
        return 20.0

    # Filter to lookback period
    cutoff = date.today() - timedelta(days=lookback_years * 365)
    recent = []
    for d in dividend_history:
        try:
            div_date = date.fromisoformat(str(d.get("date", d.get("paymentDate", "")))[:10])
            if div_date >= cutoff:
                recent.append(div_date)
        except (ValueError, TypeError):
            continue

    if not recent:
        return 20.0

    # Expect quarterly payments (4/year) or semi-annual (2/year) or annual (1/year)
    payments_per_year = len(recent) / lookback_years
    expected_per_year = max(1, round(payments_per_year))

    total_expected = expected_per_year * lookback_years
    coverage = min(1.0, len(recent) / total_expected)

    # Check for recent cuts (no payment in last 12 months when expected)
    one_year_ago = date.today() - timedelta(days=365)
    recent_payments = [d for d in recent if d >= one_year_ago]
    has_recent = len(recent_payments) >= max(1, expected_per_year // 2)

    base_score = coverage * 80.0 + 20.0  # Maps coverage [0,1] to [20, 100]
    if not has_recent:
        base_score = max(20.0, base_score - 30.0)  # Penalty for recent gap

    return round(base_score, 1)


def _score_payout_ratio(payout_ratio: float | None) -> float:
    """Score payout ratio — sustainability check.

    Ratios above 80% are increasingly penalized; below 50% is ideal.
    """
    if payout_ratio is None:
        return 50.0
    if payout_ratio < 0:
        return 30.0  # Negative earnings
    if payout_ratio <= 40:
        return 90.0  # Very sustainable
    if payout_ratio <= 60:
        return 80.0  # Healthy
    if payout_ratio <= 75:
        return 65.0  # Acceptable
    if payout_ratio <= 90:
        return 45.0  # Stretched
    if payout_ratio <= 100:
        return 30.0  # At or beyond earnings
    return 15.0  # Paying more than earnings — unsustainable


def _score_dividend_growth(dividend_history: list[dict[str, Any]]) -> float:
    """Score dividend growth trend over available history."""
    if len(dividend_history) < 2:
        return 50.0

    # Extract amounts chronologically
    amounts = []
    for d in sorted(dividend_history, key=lambda x: str(x.get("date", "")))[:20]:
        amt = d.get("dividend") or d.get("adjDividend") or d.get("amount", 0)
        try:
            amounts.append(float(amt))
        except (ValueError, TypeError):
            continue

    if len(amounts) < 2:
        return 50.0

    # Compare recent average vs older average
    mid = len(amounts) // 2
    old_avg = sum(amounts[:mid]) / mid if mid > 0 else 0
    new_avg = sum(amounts[mid:]) / (len(amounts) - mid) if (len(amounts) - mid) > 0 else 0

    if old_avg <= 0:
        return 50.0

    growth_pct = ((new_avg - old_avg) / old_avg) * 100

    if growth_pct > 20:
        return 90.0
    if growth_pct > 10:
        return 80.0
    if growth_pct > 5:
        return 70.0
    if growth_pct > 0:
        return 55.0
    if growth_pct > -10:
        return 40.0
    return 25.0  # Significant dividend decline


# ── Main scoring function ──────────────────────────────────────────────

def score_dividend(
    dividend_yield: float | None,
    dividend_history: list[dict[str, Any]],
    payout_ratio: float | None = None,
    is_crypto: bool = False,
    is_bond: bool = False,
) -> tuple[float, DividendBreakdown]:
    """Compute a normalised dividend score (0–100).

    Args:
        dividend_yield: current annual dividend yield as percentage
        dividend_history: list of historical dividend payments
        payout_ratio: payout ratio as percentage (0-100)
        is_crypto: crypto gets a neutral score
        is_bond: bonds treat "coupon" as dividend

    Returns (score, breakdown).
    """
    # Non-dividend assets get a neutral score
    if is_crypto:
        return 50.0, DividendBreakdown(details={"note": "Crypto — dividends N/A"})

    breakdown = DividendBreakdown()

    breakdown.yield_score = _score_yield(dividend_yield)
    breakdown.regularity_score = _score_regularity(dividend_history)
    breakdown.payout_ratio_score = _score_payout_ratio(payout_ratio)
    breakdown.growth_score = _score_dividend_growth(dividend_history)

    # Weighted aggregate
    weights = {
        "yield": 0.35,
        "regularity": 0.25,
        "payout_ratio": 0.20,
        "growth": 0.20,
    }

    # For bonds, regularity and yield matter more
    if is_bond:
        weights = {
            "yield": 0.45,
            "regularity": 0.30,
            "payout_ratio": 0.10,
            "growth": 0.15,
        }

    score = (
        weights["yield"] * breakdown.yield_score
        + weights["regularity"] * breakdown.regularity_score
        + weights["payout_ratio"] * breakdown.payout_ratio_score
        + weights["growth"] * breakdown.growth_score
    )

    breakdown.details = {
        "dividend_yield": dividend_yield,
        "history_count": len(dividend_history),
        "payout_ratio": payout_ratio,
        "is_bond": is_bond,
    }

    return round(score, 1), breakdown
