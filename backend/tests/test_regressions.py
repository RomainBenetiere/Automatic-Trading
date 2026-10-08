"""Regression tests for the issues found in the 2026-10-08 deployment test."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.analysis.composite import compute_composite
from app.analysis.fundamental import score_fundamental
from app.collectors.ghostfolio import GhostfolioClient
from app.execution.paper_trader import PaperTrader
from app.execution.strategy import TradeAction, decide_crypto_action
from app.models.order import Order, OrderSide, OrderStatus
from app.models.position import AssetType


# ── #1 Ghostfolio parser: null assetClass crashed the sync ──────────────

@pytest.mark.asyncio
async def test_ghostfolio_holdings_handles_nulls_and_classes(monkeypatch):
    payload = {
        "holdings": [
            {"symbol": "AAPL", "assetClass": "EQUITY", "assetSubClass": "STOCK", "quantity": 2},
            {"symbol": "XYZ", "assetClass": None, "assetSubClass": None, "quantity": None},
            {"symbol": "BTCEUR", "assetClass": "LIQUIDITY", "assetSubClass": "CRYPTOCURRENCY", "quantity": 1},
            {"symbol": "OAT", "assetClass": "FIXED_INCOME", "assetSubClass": None, "quantity": 3},
            {"symbol": "IWDA", "assetClass": "EQUITY", "assetSubClass": "ETF", "quantity": 4},
            {"symbol": "EUR", "assetClass": "LIQUIDITY", "assetSubClass": "CASH", "quantity": 100},
        ]
    }
    client = GhostfolioClient(base_url="http://x", security_token="t")

    async def fake_get(path, params=None):
        if path == "/api/v1/account":
            return {"accounts": [{"id": "1", "name": "pea"}]}
        return payload

    monkeypatch.setattr(client, "_get", fake_get)
    holdings = {h["symbol"]: h for h in await client.get_holdings()}
    await client.close()

    assert "EUR" not in holdings  # cash skipped
    assert holdings["AAPL"]["asset_type"] == AssetType.STOCK
    assert holdings["XYZ"]["asset_type"] == AssetType.STOCK
    assert holdings["XYZ"]["quantity"] == 0.0
    assert holdings["BTCEUR"]["asset_type"] == AssetType.CRYPTO
    assert holdings["OAT"]["asset_type"] == AssetType.BOND
    assert holdings["IWDA"]["asset_type"] == AssetType.ETF


# ── #3 FMP /stable field names ──────────────────────────────────────────

def test_fundamental_reads_stable_field_names():
    stable_ratios = [{
        "priceToEarningsRatio": 8.0,     # → 90
        "priceToBookRatio": 0.8,         # → 85
        "debtToEquityRatio": 0.2,        # → 90
        "operatingProfitMargin": 0.35,   # → 90
    }]
    stable_metrics = [{"evToEBITDA": 6.0}]  # → 85
    _, b = score_fundamental(stable_metrics, stable_ratios, news=[])
    assert (b.pe_score, b.pb_score, b.ev_ebitda_score, b.debt_score, b.margin_score) == (
        90.0, 85.0, 85.0, 90.0, 90.0,
    )


# ── #4 Crypto weighting + minimum order size ────────────────────────────

def test_crypto_technical_only_reaches_strong_buy():
    result = compute_composite(80.0, 50.0, 50.0, "crypto", weight_override=(1.0, 0.0, 0.0))
    assert result.composite_score == 80.0
    assert result.signal == "strong_buy"


def _buy_signal():
    return compute_composite(67.5, 50.0, 50.0, "crypto", weight_override=(1.0, 0.0, 0.0))


def test_small_portfolio_buy_bumped_to_minimum():
    # €125 × 3% = €3.75 < €5, but the 5% cap allows €6.25 → bump to €5
    action = decide_crypto_action("ADA-EUR", _buy_signal(), 0.0, 125.0, 125.0, 0.5)
    assert action is not None and action.quote_amount_eur == 5.0


def test_tiny_portfolio_buy_skipped():
    # €60 × 5% cap = €3 < €5 → cannot place a valid order
    assert decide_crypto_action("ADA-EUR", _buy_signal(), 0.0, 60.0, 60.0, 0.5) is None


# ── #5 Paper portfolio is simulated, not the real Bitvavo balance ───────

@pytest.mark.asyncio
async def test_paper_portfolio_buy_then_sell(db):
    trader = PaperTrader(db)
    prices = {"ADA-EUR": 0.50}
    price_fn = prices.get

    state = await trader.get_paper_state(price_fn)
    assert state["cash_eur"] == 1000.0 and state["portfolio_value_eur"] == 1000.0

    buy = TradeAction(symbol="ADA-EUR", side="buy", quote_amount_eur=30.0, reason="test buy")
    order = await trader.execute_action(buy, 0.50, 1000.0)
    assert order.status == OrderStatus.PAPER

    state = await trader.get_paper_state(price_fn)
    assert state["cash_eur"] == pytest.approx(970.0)
    assert state["positions"]["ADA-EUR"]["quantity"] == pytest.approx(60.0)

    prices["ADA-EUR"] = 0.60  # +20%
    sell = TradeAction(symbol="ADA-EUR", side="sell", quantity=60.0, reason="test sell")
    await trader.execute_action(sell, 0.60, 1006.0)

    state = await trader.get_paper_state(price_fn)
    assert state["positions"] == {}
    assert state["realised_pnl_eur"] == pytest.approx(6.0)
    assert state["cash_eur"] == pytest.approx(1006.0)


@pytest.mark.asyncio
async def test_global_budget_counts_open_paper_lots(db):
    db.add(Order(
        symbol="BTC-EUR", side=OrderSide.BUY, quantity=0.01, price=70000,
        order_value_eur=990.0, status=OrderStatus.PAPER, paper_mode=True,
        executed_at=datetime.utcnow(),
    ))
    await db.flush()
    check = await PaperTrader(db).guardrails.check_global_budget(20.0)
    assert not check.passed  # 990 + 20 > 1000
