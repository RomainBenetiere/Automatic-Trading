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


# ── Yahoo Finance collector maps to FMP-shaped payloads ─────────────────

def test_yahoo_client_maps_to_fmp_shapes():
    import asyncio
    import types

    import pandas as pd

    from app.analysis.fundamental import score_fundamental
    from app.collectors import yahoo

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            self.info = {
                "trailingPE": 12.0, "priceToBook": 1.5, "enterpriseToEbitda": 9.0,
                "operatingMargins": 0.25, "debtToEquity": 40.0, "payoutRatio": 0.5,
                "trailingAnnualDividendYield": 0.03, "currentPrice": 100.0,
                "netExpenseRatio": 0.2, "totalAssets": 1e9,
            }
            cols = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]
            self.income_stmt = pd.DataFrame(
                {cols[0]: [110.0, 1100.0], cols[1]: [100.0, 1000.0]},
                index=["Net Income", "Total Revenue"],
            )
            self.dividends = pd.Series([1.0, 1.1], index=pd.to_datetime(["2024-06-01", "2025-06-01"]))
            self.news = [{"content": {"title": "Record profit", "summary": "strong",
                                      "pubDate": "2026-01-01T00:00:00Z",
                                      "canonicalUrl": {"url": "http://x"},
                                      "provider": {"displayName": "Reuters"}}}]

    client = yahoo.YahooFinanceClient.__new__(yahoo.YahooFinanceClient)
    client._yf = types.SimpleNamespace(Ticker=FakeTicker, Search=None)
    client._symbol_map = yahoo._parse_symbol_map("CW8=CW8.PA")
    client._resolved, client._tickers, client._info = {}, {}, {}
    client._request_count, client.last_error = 0, None

    async def run():
        assert await client._resolve("CW8") == "CW8.PA"
        km = await client.get_key_metrics("AI.PA")
        r = await client.get_financial_ratios("AI.PA")
        etf = await client.get_etf_info("CW8")
        divs = await client.get_dividend_history("AI.PA")
        news = await client.get_stock_news("AI.PA")
        return km, r, etf, divs, news

    km, r, etf, divs, news = asyncio.run(run())
    assert km[0]["peRatio"] == 12.0 and km[0]["dividendYield"] == 0.03
    assert abs(km[0]["netIncomePerShareGrowth"] - 0.10) < 1e-9
    assert r[0]["debtEquityRatio"] == 0.40  # Yahoo % → ratio
    assert abs(etf["expenseRatio"] - 0.002) < 1e-12  # 0.2 % → fraction
    assert divs[0]["date"] == "2025-06-01" and divs[0]["dividend"] == 1.1  # newest first
    assert news[0]["title"] == "Record profit" and news[0]["site"] == "Reuters"

    score, breakdown = score_fundamental(km, r, news)
    assert breakdown.pe_score == 80.0 and breakdown.debt_score == 75.0
    assert score > 60


def test_accumulating_etf_ignores_dividend_score():
    from app.analysis.composite import compute_composite

    # Regular ETF with dividend score
    res_regular = compute_composite(
        technical_score=60.0,
        fundamental_score=70.0,
        dividend_score=20.0,
        asset_type="etf",
        is_accumulating=False,
    )
    # 0.35 * 60 + 0.30 * 70 + 0.35 * 20 = 21 + 21 + 7 = 49.0
    assert res_regular.composite_score == 49.0
    assert res_regular.weights["dividend"] == 0.35

    # Accumulating ETF: dividend score is ignored, weights redistributed between tech and fund (35:30 -> 53.8% : 46.2%)
    res_acc = compute_composite(
        technical_score=60.0,
        fundamental_score=70.0,
        dividend_score=None,
        asset_type="etf",
        is_accumulating=True,
    )
    assert res_acc.weights["dividend"] == 0.0
    # Expected: (35/65)*60 + (30/65)*70 = 32.31 + 32.31 = 64.6
    assert abs(res_acc.composite_score - 64.6) < 0.2
    assert res_acc.signal == "buy"  # was dragged down to hold/reduce without this fix


def test_resolve_account_type_pattern_matching():
    from app.collectors.ghostfolio import resolve_account_type
    from app.models.position import AccountType

    assert resolve_account_type("PEE BNP") == AccountType.PEE
    assert resolve_account_type("Plan d'Epargne Entreprise") == AccountType.PEE
    assert resolve_account_type("PER FORTUNEO") == AccountType.PER
    assert resolve_account_type("PER LINXEA") == AccountType.PER
    assert resolve_account_type("PERO BNP") == AccountType.PER
    assert resolve_account_type("PEA BOURSORAMA") == AccountType.PEA
    assert resolve_account_type("Assurance Vie Linxea") == AccountType.ASSURANCE_VIE
    assert resolve_account_type("AV Spirica") == AccountType.ASSURANCE_VIE
    assert resolve_account_type("Bitvavo Crypto") == AccountType.CRYPTO
    assert resolve_account_type("Compte Titres Ordinaire") == AccountType.BROKERAGE
    assert resolve_account_type("CTO Degiro") == AccountType.BROKERAGE
    assert resolve_account_type("Unknown Broker") == AccountType.BROKERAGE


@pytest.mark.asyncio
async def test_ghostfolio_holdings_includes_account_name(monkeypatch):
    from app.collectors.ghostfolio import GhostfolioClient
    from app.models.position import AccountType

    payload = {
        "holdings": [
            {"symbol": "CW8", "assetClass": "EQUITY", "assetSubClass": "ETF", "quantity": 10},
        ]
    }
    client = GhostfolioClient(base_url="http://x", security_token="t")

    async def fake_get(path, params=None):
        if path == "/api/v1/account":
            return {"accounts": [{"id": "acc-1", "name": "PEE BNP"}]}
        return payload

    monkeypatch.setattr(client, "_get", fake_get)
    holdings = await client.get_holdings()
    await client.close()

    assert len(holdings) == 1
    assert holdings[0]["symbol"] == "CW8"
    assert holdings[0]["account_type"] == AccountType.PEE
    assert holdings[0]["account_name"] == "PEE BNP"


@pytest.mark.asyncio
async def test_init_db_auto_migration():
    from app.database import init_db, engine
    from sqlalchemy import text

    await init_db()

    async with engine.connect() as conn:
        res = await conn.execute(text("PRAGMA table_info(positions)"))
        cols = [r[1] for r in res.fetchall()]
        assert "account_name" in cols

        res = await conn.execute(text("PRAGMA table_info(recommendations)"))
        cols = [r[1] for r in res.fetchall()]
        assert "account_name" in cols

        res = await conn.execute(text("PRAGMA table_info(orders)"))
        cols = [r[1] for r in res.fetchall()]
        assert "stop_loss_order_id" in cols


# ── Native Bitvavo Stop-Loss & 15-Minute Trailing Stops ─────────────────

def test_bitvavo_place_stop_loss_order():
    from app.collectors.bitvavo import BitvavoClient

    client = BitvavoClient(api_key="k", api_secret="s")
    captured = {}

    def fake_place_order(market, side, order_type, body):
        captured["market"] = market
        captured["side"] = side
        captured["order_type"] = order_type
        captured["body"] = body
        return {"orderId": "sl-12345", "status": "awaitingTrigger"}

    client._bitvavo.placeOrder = fake_place_order

    res = client.place_stop_loss_order(
        market="BTC-EUR",
        side="sell",
        amount=0.012345678,
        trigger_price=64500.50,
    )
    assert res.get("orderId") == "sl-12345"
    assert captured["market"] == "BTC-EUR"
    assert captured["side"] == "sell"
    assert captured["order_type"] == "stopLoss"
    assert captured["body"]["orderType"] == "stopLoss"
    assert captured["body"]["triggerAmount"] == "64500.50"
    assert captured["body"]["amount"] == "0.01234568"
    assert captured["body"]["triggerReference"] == "last"


@pytest.mark.asyncio
async def test_live_trader_places_stop_loss_and_trailing_stop_updates(db, monkeypatch):
    from app.collectors.bitvavo import BitvavoClient
    from app.config import settings
    from app.execution.live_trader import LiveTrader

    monkeypatch.setattr(settings, "crypto_live_mode", True)

    client = BitvavoClient(api_key="k", api_secret="s")
    placed_orders = []
    cancelled_orders = []

    def fake_place_market(market, side, amount=None, quote_amount=None):
        return {"orderId": "buy-100", "price": "60000.0", "filledAmount": "0.01"}

    def fake_place_stop(market, side, amount, trigger_price):
        placed_orders.append({"market": market, "side": side, "amount": amount, "trigger_price": trigger_price})
        return {"orderId": f"sl-{len(placed_orders)}"}

    def fake_cancel_order(market, order_id):
        cancelled_orders.append({"market": market, "order_id": order_id})
        return {"orderId": order_id}

    prices = {"BTC-EUR": 60000.0}

    def fake_get_price(market):
        return prices.get(market)

    client.place_market_order = fake_place_market
    client.place_stop_loss_order = fake_place_stop
    client.cancel_order = fake_cancel_order
    client.get_ticker_price = fake_get_price
    client.get_order_status = lambda m, oid: {"status": "awaitingTrigger"}

    trader = LiveTrader(db, client)

    # 1. Buy action -> places buy order and immediately sends native stop-loss
    action = TradeAction(
        symbol="BTC-EUR",
        side="buy",
        quote_amount_eur=600.0,
        reason="Test buy",
    )
    order = await trader.execute_action(action, current_price=60000.0, portfolio_value_eur=20000.0)

    assert order is not None
    assert order.status == OrderStatus.FILLED
    assert order.stop_loss_order_id == "sl-1"
    assert len(placed_orders) == 1
    # Stop-loss at 5% below 60000 is 57000
    assert placed_orders[0]["trigger_price"] == 57000.0

    # 2. Check open positions with price increase (price rises to 65000, below 69000 take-profit)
    prices["BTC-EUR"] = 65000.0
    await trader.check_open_positions()

    # Trailing stop should have been updated: old cancelled, new stop placed
    assert len(cancelled_orders) == 1
    assert cancelled_orders[0]["order_id"] == "sl-1"
    assert len(placed_orders) == 2
    # 3% trailing stop from 65000 is 65000 * 0.97 = 63050
    assert placed_orders[1]["trigger_price"] == 63050.0
    assert order.stop_loss_order_id == "sl-2"

    # 3. Check open positions when native stop fills on Bitvavo
    client.get_order_status = lambda m, oid: {"status": "filled", "price": "63050.0"}
    triggered = await trader.check_open_positions()

    assert len(triggered) == 1
    assert triggered[0]["reason"] == "bitvavo_native_stop_loss_filled"
    assert order.closed_at is not None
    assert order.realised_pnl == pytest.approx((63050.0 - 60000.0) * 0.01)


@pytest.mark.asyncio
async def test_paper_trader_stops_and_4h_config(db):
    from app.config import settings
    from app.execution.paper_trader import PaperTrader
    from app.scheduler.jobs import run_crypto_stops_check_job

    assert settings.crypto_candle_interval == "4h"

    trader = PaperTrader(db)
    prices = {"BTC-EUR": 50000.0}

    # 1. Create paper buy (take-profit is 50000 * 1.15 = 57500)
    action = TradeAction(
        symbol="BTC-EUR",
        side="buy",
        quote_amount_eur=500.0,
        reason="Test paper buy",
    )
    order = await trader.execute_action(action, current_price=50000.0, portfolio_value_eur=20000.0)
    assert order is not None
    assert order.status == OrderStatus.PAPER
    assert order.trailing_stop_price == 47500.0  # 50000 * 0.95

    # 2. Price climbs to 55000 (below 57500 TP) -> trailing stop ratchets to 55000 * 0.97 = 53350
    prices["BTC-EUR"] = 55000.0
    await trader.check_open_positions(prices.get)
    assert order.trailing_stop_price == 53350.0
    assert order.closed_at is None

    # 3. Price drops to 53000 (< 53350) -> triggers trailing stop
    prices["BTC-EUR"] = 53000.0
    triggered = await trader.check_open_positions(prices.get)
    assert len(triggered) == 1
    assert order.closed_at is not None
    assert order.realised_pnl is not None


# ── #16 Bitvavo Top Markets & Screener ────────────────────────────────

def test_bitvavo_get_top_markets_filters_stables_and_sorts(monkeypatch):
    from app.collectors.bitvavo import BitvavoClient

    client = BitvavoClient(api_key="", api_secret="")

    mock_ticker_data = [
        {"market": "USDT-EUR", "last": "1.0", "open": "1.0", "high": "1.01", "low": "0.99", "volume": "50000000", "volumeQuote": "50000000"},
        {"market": "USDC-EUR", "last": "1.0", "open": "1.0", "high": "1.01", "low": "0.99", "volume": "20000000", "volumeQuote": "20000000"},
        {"market": "BTC-USD", "last": "65000", "open": "64000", "high": "66000", "low": "63000", "volume": "100", "volumeQuote": "6500000"},
        {"market": "BTC-EUR", "last": "60000", "open": "58000", "high": "61000", "low": "57500", "volume": "200", "volumeQuote": "12000000"},
        {"market": "ETH-EUR", "last": "3000", "open": "2900", "high": "3050", "low": "2850", "volume": "2000", "volumeQuote": "6000000"},
        {"market": "SOL-EUR", "last": "150", "open": "140", "high": "155", "low": "138", "volume": "50000", "volumeQuote": "7500000"},
    ]

    monkeypatch.setattr(client._bitvavo, "ticker24h", lambda opts: mock_ticker_data)

    markets = client.get_top_markets(limit=2, quote="EUR", exclude_stables=True)

    # Stables (USDT, USDC) and non-EUR (BTC-USD) must be excluded
    # Remaining: BTC-EUR (12M), SOL-EUR (7.5M), ETH-EUR (6M)
    # Sorted descending by volumeQuote, limit 2: BTC-EUR first, SOL-EUR second
    assert len(markets) == 2
    assert markets[0]["symbol"] == "BTC"
    assert markets[0]["market"] == "BTC-EUR"
    assert markets[0]["volume_eur"] == 12000000.0
    assert markets[0]["change_24h_pct"] == pytest.approx(3.45, rel=1e-2)

    assert markets[1]["symbol"] == "SOL"
    assert markets[1]["market"] == "SOL-EUR"
    assert markets[1]["volume_eur"] == 7500000.0


@pytest.mark.asyncio
async def test_crypto_screener_api_endpoint(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    # Mock BitvavoClient methods
    mock_markets = [
        {"symbol": "BTC", "market": "BTC-EUR", "price": 60000.0, "volume_eur": 1000000.0, "change_24h_pct": 2.5},
        {"symbol": "ETH", "market": "ETH-EUR", "price": 3000.0, "volume_eur": 500000.0, "change_24h_pct": -1.2},
    ]

    from app.collectors.bitvavo import BitvavoClient
    monkeypatch.setattr(BitvavoClient, "get_top_markets", lambda self, limit=30, quote="EUR", exclude_stables=True: mock_markets)
    monkeypatch.setattr(BitvavoClient, "get_balances", lambda self: [{"symbol": "BTC", "total": 0.05}])
    monkeypatch.setattr(BitvavoClient, "get_candles", lambda self, market, interval="4h", limit=100: [])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/crypto/screener?limit=10&with_scores=false&force_refresh=true")
        assert response.status_code == 200
        data = response.json()
        assert "markets" in data
        assert "current_basket" in data
        assert "technical_weights" in data
        assert "rsi" in data["technical_weights"]
        assert data["technical_weights"]["rsi"] == 1.0
        btc = next(m for m in data["markets"] if m["symbol"] == "BTC")
        assert btc["in_portfolio"] is True
        eth = next(m for m in data["markets"] if m["symbol"] == "ETH")
        assert eth["in_portfolio"] is False


def test_score_technical_with_custom_weights():
    import pandas as pd
    from app.analysis.technical import score_technical

    # Create dummy DataFrame with 30 rows
    data = {
        "open": [100.0 + i for i in range(30)],
        "high": [105.0 + i for i in range(30)],
        "low": [95.0 + i for i in range(30)],
        "close": [102.0 + i for i in range(30)],
        "volume": [1000.0 for _ in range(30)],
        "sma_short": [120.0 for _ in range(30)],
        "sma_long": [100.0 for _ in range(30)],  # sma_cross = +1.0
        "ema_fast": [120.0 for _ in range(30)],
        "ema_slow": [100.0 for _ in range(30)],  # ema_cross = +1.0
        "rsi": [80.0 for _ in range(30)],        # rsi = -1.0 (overbought)
    }
    df = pd.DataFrame(data)

    # 1. Balanced weights (1.0 each for sma, ema, rsi)
    # signals: +1, +1, -1 -> avg = +1/3 -> score = (1/3 + 1.5)/3 * 100 = ~61.1
    s_balanced, sigs = score_technical(df, weights={"sma_cross": 1.0, "ema_cross": 1.0, "rsi": 1.0})
    assert s_balanced > 55.0

    # 2. Heavy RSI weight (e.g. 10.0 for rsi vs 1.0 for sma/ema)
    # RSI (-1.0) dominates -> avg should be strongly negative -> score should drop significantly
    s_heavy_rsi, _ = score_technical(df, weights={"sma_cross": 1.0, "ema_cross": 1.0, "rsi": 10.0})
    assert s_heavy_rsi < s_balanced
    assert s_heavy_rsi < 35.0


@pytest.mark.asyncio
async def test_crypto_daily_job_multiple_runs_and_stocks_job_preserve_crypto_scores(db, monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import timedelta
    from sqlalchemy import select
    from app.config import settings
    from app.collectors.bitvavo import BitvavoClient
    from app.collectors.ghostfolio import GhostfolioClient
    from app.models.score import Score
    from app.models.position import AccountType, AssetType
    from app.scheduler import jobs as scheduler_jobs

    @asynccontextmanager
    async def fake_session():
        yield db

    monkeypatch.setattr(scheduler_jobs, "async_session", fake_session)

    # Mock Bitvavo candles + prices
    now = datetime.utcnow()
    dummy_candles = [
        {
            "datetime": now - timedelta(hours=4 * (40 - i)),
            "open": 100.0 + i,
            "high": 105.0 + i,
            "low": 95.0 + i,
            "close": 102.0 + i,
            "volume": 1000.0,
        }
        for i in range(40)
    ]
    monkeypatch.setattr(BitvavoClient, "get_candles", lambda self, market, interval="4h", limit=200: dummy_candles)
    monkeypatch.setattr(BitvavoClient, "get_ticker_price", lambda self, symbol: 140.0)

    # 1st run with initial 5 cryptos
    monkeypatch.setattr(settings, "crypto_basket", "BTC-EUR,ETH-EUR,SOL-EUR,XRP-EUR,ADA-EUR")
    res1 = await scheduler_jobs.run_crypto_daily_job()
    assert len(res1["actions"]) == 5
    assert all("error" not in a for a in res1["actions"])

    # 2nd run on the same day after adding new cryptos to CRYPTO_BASKET
    full_basket = "BTC-EUR,ETH-EUR,SOL-EUR,XRP-EUR,ADA-EUR,BNB-EUR,TAO-EUR,AAVE-EUR,ONDO-EUR,ICNT-EUR,EIGEN-EUR,GTC-EUR"
    monkeypatch.setattr(settings, "crypto_basket", full_basket)
    res2 = await scheduler_jobs.run_crypto_daily_job()
    assert len(res2["actions"]) == 12
    assert all("error" not in a for a in res2["actions"])

    scores_after_crypto = (await db.execute(select(Score))).scalars().all()
    assert {s.symbol for s in scores_after_crypto} == set(full_basket.split(","))

    # Now run stocks weekly job on the same day and ensure crypto scores are NOT wiped out
    async def fake_holdings(self):
        return [
            {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "asset_type": AssetType.STOCK,
                "account_type": AccountType.CTO,
                "account_name": "CTO",
                "quantity": 10.0,
                "avg_buy_price": 150.0,
                "current_price": 180.0,
                "total_value": 1800.0,
                "unrealized_pnl": 300.0,
                "unrealized_pnl_pct": 20.0,
                "currency": "EUR",
                "snapshot_date": now.date(),
            }
        ]

    monkeypatch.setattr(GhostfolioClient, "get_holdings", fake_holdings)
    await scheduler_jobs.run_stocks_weekly_job()

    scores_after_stocks = (await db.execute(select(Score))).scalars().all()
    scored_symbols = {s.symbol for s in scores_after_stocks}
    for crypto_sym in full_basket.split(","):
        assert crypto_sym in scored_symbols


def test_custom_buy_and_strong_buy_pct_from_env(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "crypto_buy_pct", 7.5)
    monkeypatch.setattr(settings, "crypto_strong_buy_pct", 12.0)

    buy_res = compute_composite(68.0, 50.0, 50.0, "crypto", weight_override=(1.0, 0.0, 0.0))
    strong_buy_res = compute_composite(80.0, 50.0, 50.0, "crypto", weight_override=(1.0, 0.0, 0.0))

    act_buy = decide_crypto_action("BTC-EUR", buy_res, 0.0, 1000.0, 1000.0, 50000.0)
    act_strong = decide_crypto_action("BTC-EUR", strong_buy_res, 0.0, 1000.0, 1000.0, 50000.0)

    assert act_buy is not None and act_buy.quote_amount_eur == 75.0
    assert act_strong is not None and act_strong.quote_amount_eur == 120.0


def test_two_stage_optimizer_optimizes_windows_and_weights():
    import numpy as np
    import pandas as pd
    from app.analysis.optimizer import optimize_parameters, INDICATOR_KEYS

    rng = np.random.default_rng(123)
    n = 150
    # Upward trend with cyclical waves so indicators have clear signal opportunities
    t = np.linspace(0, 6 * np.pi, n)
    close = 100.0 + np.linspace(0, 35, n) + 8.0 * np.sin(t) + rng.normal(0, 0.5, n)
    df = pd.DataFrame({
        "open": close - 0.5,
        "high": close + 1.5,
        "low": close - 1.5,
        "close": close,
        "volume": 1000.0 + 200.0 * np.cos(t),
    })

    opt = optimize_parameters(df, "TEST-EUR")
    assert "weights" in opt.best_params
    weights = opt.best_params["weights"]
    for key in INDICATOR_KEYS:
        assert key in weights
        assert 0.0 <= weights[key] <= 3.0
    assert opt.oos_return >= 0.0


@pytest.mark.asyncio
async def test_indicator_config_history_3_months_retention(db, monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import timedelta
    from sqlalchemy import select
    from app.config import settings
    from app.collectors.bitvavo import BitvavoClient
    from app.models.indicator_config import IndicatorConfigHistory
    from app.scheduler import jobs as scheduler_jobs

    @asynccontextmanager
    async def fake_session():
        yield db

    monkeypatch.setattr(scheduler_jobs, "async_session", fake_session)
    monkeypatch.setattr(settings, "crypto_basket", "BTC-EUR")

    # Insert an expired history entry (100 days old > 90 days)
    old_entry = IndicatorConfigHistory(
        symbol="BTC-EUR",
        indicator_name="all",
        parameters='{"ema_fast": 12}',
        oos_sharpe=0.5,
        oos_sortino=0.5,
        oos_return=0.01,
        recorded_at=datetime.utcnow() - timedelta(days=100),
    )
    db.add(old_entry)
    await db.commit()

    now = datetime.utcnow()
    dummy_candles = [
        {
            "datetime": now - timedelta(hours=4 * (80 - i)),
            "open": 100.0 + i * 0.5,
            "high": 102.0 + i * 0.5,
            "low": 98.0 + i * 0.5,
            "close": 101.0 + i * 0.5,
            "volume": 1000.0,
        }
        for i in range(80)
    ]
    monkeypatch.setattr(BitvavoClient, "get_candles", lambda self, market, interval="4h", limit=500: dummy_candles)

    await scheduler_jobs.run_optimizer_weekly_job()

    rows = (await db.execute(select(IndicatorConfigHistory))).scalars().all()
    assert len(rows) == 1
    assert rows[0].symbol == "BTC-EUR"
    assert (now - rows[0].recorded_at).total_seconds() < 60

