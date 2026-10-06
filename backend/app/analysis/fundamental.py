"""Fundamental analysis module — valuation, growth, quality, and news scoring."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FundamentalBreakdown:
    """Breakdown of the fundamental score components."""

    pe_score: float = 50.0
    pb_score: float = 50.0
    ev_ebitda_score: float = 50.0
    earnings_growth_score: float = 50.0
    margin_score: float = 50.0
    debt_score: float = 50.0
    news_sentiment_score: float = 50.0
    etf_cost_score: float = 50.0
    details: dict = field(default_factory=dict)


def _score_pe(pe: float | None) -> float:
    """Score P/E ratio: lower is better, with guardrails."""
    if pe is None or pe <= 0:
        return 40.0  # Negative earnings → slight penalty
    if pe < 10:
        return 90.0
    if pe < 15:
        return 80.0
    if pe < 20:
        return 65.0
    if pe < 30:
        return 50.0
    if pe < 50:
        return 35.0
    return 20.0  # Very high P/E


def _score_pb(pb: float | None) -> float:
    """Score P/B ratio: lower is better for value."""
    if pb is None or pb <= 0:
        return 50.0
    if pb < 1.0:
        return 85.0
    if pb < 2.0:
        return 70.0
    if pb < 3.0:
        return 55.0
    if pb < 5.0:
        return 40.0
    return 25.0


def _score_ev_ebitda(ev_ebitda: float | None) -> float:
    """Score EV/EBITDA: lower suggests better value."""
    if ev_ebitda is None or ev_ebitda <= 0:
        return 50.0
    if ev_ebitda < 8:
        return 85.0
    if ev_ebitda < 12:
        return 70.0
    if ev_ebitda < 16:
        return 55.0
    if ev_ebitda < 25:
        return 40.0
    return 25.0


def _score_earnings_growth(growth_rates: list[float]) -> float:
    """Score earnings growth trajectory."""
    if not growth_rates:
        return 50.0

    avg_growth = sum(growth_rates) / len(growth_rates)
    if avg_growth > 20:
        return 90.0
    if avg_growth > 10:
        return 75.0
    if avg_growth > 5:
        return 60.0
    if avg_growth > 0:
        return 50.0
    if avg_growth > -5:
        return 40.0
    return 25.0


def _score_margins(operating_margin: float | None) -> float:
    """Score operating margin quality and stability."""
    if operating_margin is None:
        return 50.0
    if operating_margin > 30:
        return 90.0
    if operating_margin > 20:
        return 75.0
    if operating_margin > 10:
        return 60.0
    if operating_margin > 0:
        return 45.0
    return 25.0  # Negative margin


def _score_debt(debt_equity: float | None) -> float:
    """Score debt-to-equity ratio: lower is generally safer."""
    if debt_equity is None:
        return 50.0
    if debt_equity < 0.3:
        return 90.0
    if debt_equity < 0.5:
        return 75.0
    if debt_equity < 1.0:
        return 60.0
    if debt_equity < 2.0:
        return 40.0
    return 20.0  # Heavily leveraged


def _score_etf_cost(expense_ratio: float | None, aum: float | None) -> float:
    """Score ETF cost efficiency (expense ratio + AUM threshold)."""
    score = 50.0

    if expense_ratio is not None:
        if expense_ratio < 0.1:
            score = 90.0
        elif expense_ratio < 0.3:
            score = 75.0
        elif expense_ratio < 0.5:
            score = 60.0
        elif expense_ratio < 1.0:
            score = 40.0
        else:
            score = 20.0

    # Penalize very small AUM (liquidity risk)
    if aum is not None and aum < 50_000_000:  # < 50M
        score = max(20.0, score - 15.0)

    return score


# ── News sentiment (basic keyword-based) ────────────────────────────────

POSITIVE_KEYWORDS = {
    "beat", "exceed", "upgrade", "growth", "profit", "record", "strong",
    "surge", "rally", "buy", "outperform", "bullish", "dividend",
    "increase", "expand", "innovation", "partnership", "acquisition",
}

NEGATIVE_KEYWORDS = {
    "miss", "downgrade", "loss", "decline", "cut", "sell", "warning",
    "weak", "bearish", "investigation", "lawsuit", "default", "debt",
    "layoff", "restructuring", "recession", "risk", "crash", "plunge",
}


def _score_news_sentiment(articles: list[dict[str, Any]]) -> float:
    """Basic keyword sentiment scoring on news headlines."""
    if not articles:
        return 50.0

    positive_count = 0
    negative_count = 0

    for article in articles[:20]:  # Cap at 20 most recent
        title = (article.get("title") or "").lower()
        text = (article.get("text") or article.get("description", "")).lower()
        combined = f"{title} {text}"

        for kw in POSITIVE_KEYWORDS:
            if kw in combined:
                positive_count += 1
                break
        for kw in NEGATIVE_KEYWORDS:
            if kw in combined:
                negative_count += 1
                break

    total = positive_count + negative_count
    if total == 0:
        return 50.0

    ratio = positive_count / total  # 0 = all negative, 1 = all positive
    return round(30.0 + ratio * 40.0, 1)  # Map to [30, 70]


# ── Main scoring function ──────────────────────────────────────────────

def score_fundamental(
    key_metrics: list[dict[str, Any]],
    ratios: list[dict[str, Any]],
    news: list[dict[str, Any]],
    etf_info: dict[str, Any] | None = None,
    is_etf: bool = False,
    is_crypto: bool = False,
) -> tuple[float, FundamentalBreakdown]:
    """Compute a normalised fundamental score (0–100).

    Args:
        key_metrics: FMP key-metrics data (list of periods)
        ratios: FMP financial-ratios data (list of periods)
        news: FMP news articles
        etf_info: FMP ETF info (if applicable)
        is_etf: whether the asset is an ETF
        is_crypto: whether the asset is a cryptocurrency

    Returns (score, breakdown).
    """
    # Crypto assets get a neutral fundamental score
    if is_crypto:
        return 50.0, FundamentalBreakdown(details={"note": "Crypto — fundamentals N/A"})

    breakdown = FundamentalBreakdown()

    # Extract latest period metrics
    latest_metrics = key_metrics[0] if key_metrics else {}
    latest_ratios = ratios[0] if ratios else {}

    # ── Valuation ──────────────────────────────────────────────────
    breakdown.pe_score = _score_pe(latest_metrics.get("peRatio"))
    breakdown.pb_score = _score_pb(latest_metrics.get("pbRatio"))
    breakdown.ev_ebitda_score = _score_ev_ebitda(
        latest_metrics.get("enterpriseValueOverEBITDA")
    )

    # ── Growth ─────────────────────────────────────────────────────
    growth_rates = []
    for period in key_metrics[:4]:  # Last 4 periods
        growth = period.get("netIncomePerShareGrowth") or period.get("revenueGrowth")
        if growth is not None:
            growth_rates.append(float(growth) * 100)  # Convert to percentage
    breakdown.earnings_growth_score = _score_earnings_growth(growth_rates)

    # ── Quality ────────────────────────────────────────────────────
    op_margin = latest_ratios.get("operatingProfitMargin")
    if op_margin is not None:
        op_margin = float(op_margin) * 100  # Convert to percentage
    breakdown.margin_score = _score_margins(op_margin)

    debt_eq = latest_ratios.get("debtEquityRatio")
    breakdown.debt_score = _score_debt(
        float(debt_eq) if debt_eq is not None else None
    )

    # ── News sentiment ─────────────────────────────────────────────
    breakdown.news_sentiment_score = _score_news_sentiment(news)

    # ── ETF-specific ───────────────────────────────────────────────
    if is_etf and etf_info:
        expense_ratio = etf_info.get("expenseRatio")
        aum = etf_info.get("aum") or etf_info.get("totalAssets")
        breakdown.etf_cost_score = _score_etf_cost(
            float(expense_ratio) * 100 if expense_ratio else None,
            float(aum) if aum else None,
        )

    # ── Weighted aggregate ─────────────────────────────────────────
    if is_etf:
        weights = {
            "pe": 0.05, "pb": 0.05, "ev_ebitda": 0.05,
            "earnings_growth": 0.10, "margin": 0.05, "debt": 0.05,
            "news_sentiment": 0.15, "etf_cost": 0.50,
        }
    else:
        weights = {
            "pe": 0.20, "pb": 0.10, "ev_ebitda": 0.15,
            "earnings_growth": 0.20, "margin": 0.15, "debt": 0.10,
            "news_sentiment": 0.10, "etf_cost": 0.0,
        }

    score = (
        weights["pe"] * breakdown.pe_score
        + weights["pb"] * breakdown.pb_score
        + weights["ev_ebitda"] * breakdown.ev_ebitda_score
        + weights["earnings_growth"] * breakdown.earnings_growth_score
        + weights["margin"] * breakdown.margin_score
        + weights["debt"] * breakdown.debt_score
        + weights["news_sentiment"] * breakdown.news_sentiment_score
        + weights["etf_cost"] * breakdown.etf_cost_score
    )

    breakdown.details = {
        "pe_ratio": latest_metrics.get("peRatio"),
        "pb_ratio": latest_metrics.get("pbRatio"),
        "ev_ebitda": latest_metrics.get("enterpriseValueOverEBITDA"),
        "growth_rates": growth_rates,
        "operating_margin_pct": op_margin,
        "debt_equity": latest_ratios.get("debtEquityRatio"),
        "news_count": len(news),
        "is_etf": is_etf,
    }

    return round(score, 1), breakdown
