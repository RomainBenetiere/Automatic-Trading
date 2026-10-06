"""Scheduled jobs — daily crypto analysis + weekly stock/ETF/bond analysis.

Integrates with FastAPI via the lifespan context manager using APScheduler.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.composite import compute_composite, weights_to_json
from app.analysis.dividend import score_dividend
from app.analysis.fundamental import score_fundamental
from app.analysis.technical import (
    classify_volatility,
    compute_indicators,
    get_params,
    score_technical,
)
from app.collectors.bitvavo import BitvavoClient
from app.collectors.fmp import FMPClient
from app.collectors.ghostfolio import GhostfolioClient
from app.config import settings
from app.database import async_session
from app.execution.paper_trader import PaperTrader
from app.execution.live_trader import LiveTrader
from app.execution.strategy import decide_crypto_action
from app.llm import get_llm_provider
from app.models.market_data import MarketData
from app.models.order import Order, OrderSide, OrderStatus
from app.models.position import AccountType, AssetType, Position
from app.models.recommendation import ActionType, Recommendation
from app.models.score import Score

logger = logging.getLogger(__name__)


# ── Synthesis prompt template ───────────────────────────────────────────

SYNTHESIS_SYSTEM_PROMPT_FR = """Tu es un conseiller financier expérimenté. 
Tu produis des synthèses concises (3-5 phrases) expliquant ta recommandation 
sur un actif financier, en te basant sur les scores techniques, fondamentaux 
et de dividendes fournis. Sois factuel, nuancé et mentionne les points clés 
qui justifient ta recommandation. Réponds en français."""

SYNTHESIS_SYSTEM_PROMPT_EN = """You are an experienced financial advisor.
You produce concise syntheses (3-5 sentences) explaining your recommendation 
on a financial asset, based on the technical, fundamental, and dividend scores 
provided. Be factual, nuanced, and mention the key points that justify your 
recommendation. Respond in English."""


def _build_synthesis_prompt(
    symbol: str,
    name: str,
    asset_type: str,
    account_type: str,
    technical_score: float,
    fundamental_score: float,
    dividend_score: float,
    composite_score: float,
    signal: str,
    details: dict | None = None,
) -> str:
    """Build the prompt for LLM narrative synthesis."""
    return f"""Analyse pour {name} ({symbol}) — {asset_type} dans le compte {account_type}:

- Score technique: {technical_score}/100
- Score fondamental: {fundamental_score}/100
- Score dividende: {dividend_score}/100
- Score composite: {composite_score}/100
- Signal: {signal.upper().replace('_', ' ')}

Détails additionnels: {json.dumps(details or {}, ensure_ascii=False, indent=2)}

Produis une synthèse de recommandation en 3-5 phrases."""


# ── Daily crypto job ────────────────────────────────────────────────────

async def run_crypto_daily_job() -> dict[str, Any]:
    """Daily crypto analysis and trading job.

    1. Fetch Bitvavo balances + candle data
    2. Compute technical indicators + scores
    3. Run strategy → generate trade actions
    4. Execute via paper or live trader
    5. Check trailing stops on existing positions
    """
    logger.info("═══ CRYPTO DAILY JOB START ═══")
    results: dict[str, Any] = {"timestamp": datetime.utcnow().isoformat(), "actions": []}

    bitvavo = BitvavoClient()
    basket = settings.crypto_basket_list

    async with async_session() as db:
        # 1. Fetch balances
        balances = bitvavo.get_balances()
        balance_map = {b["symbol"]: b for b in balances}

        # Get total portfolio value
        portfolio_value = 0.0
        for market in basket:
            base_currency = market.split("-")[0]
            bal = balance_map.get(base_currency, {})
            price = bitvavo.get_ticker_price(market)
            if price and bal:
                portfolio_value += bal.get("total", 0) * price

        # Add EUR balance
        eur_balance = balance_map.get("EUR", {}).get("available", 0)
        portfolio_value += eur_balance

        logger.info("Crypto portfolio value: €%.2f (EUR available: €%.2f)", portfolio_value, eur_balance)

        # 2. For each asset in the basket
        for market in basket:
            try:
                logger.info("── Processing %s ──", market)
                base_currency = market.split("-")[0]

                # Fetch candle data
                candles = bitvavo.get_candles(market, interval="1d", limit=200)
                if len(candles) < 20:
                    logger.warning("Not enough candle data for %s (%d)", market, len(candles))
                    continue

                # Convert to DataFrame
                df = pd.DataFrame(candles)
                df = df.rename(columns={"datetime": "date"})
                df = df.set_index("date")

                # Compute indicators
                regime = classify_volatility(df)
                params = get_params(regime)
                df = compute_indicators(df, params)

                # Score
                tech_score, tech_signals = score_technical(df)
                fund_score = 50.0  # Neutral for crypto
                div_score = 50.0   # N/A for crypto

                composite = compute_composite(
                    tech_score, fund_score, div_score, asset_type="crypto"
                )

                # Store score
                score_record = Score(
                    symbol=market,
                    date=date.today(),
                    technical_score=tech_score,
                    fundamental_score=fund_score,
                    dividend_score=div_score,
                    composite_score=composite.composite_score,
                    weights_used=weights_to_json(composite.weights),
                    signal=composite.signal,
                )
                db.add(score_record)

                # Store latest market data
                if len(df) > 0:
                    latest = df.iloc[-1]
                    md = MarketData(
                        symbol=market,
                        date=date.today(),
                        open=latest.get("open"),
                        high=latest.get("high"),
                        low=latest.get("low"),
                        close=latest.get("close"),
                        volume=latest.get("volume"),
                        rsi=latest.get("rsi"),
                        macd=latest.get("macd"),
                        macd_signal=latest.get("macd_signal"),
                        macd_histogram=latest.get("macd_histogram"),
                        bollinger_upper=latest.get("bollinger_upper"),
                        bollinger_middle=latest.get("bollinger_middle"),
                        bollinger_lower=latest.get("bollinger_lower"),
                        atr=latest.get("atr"),
                        obv=latest.get("obv"),
                    )
                    db.add(md)

                # 3. Run strategy
                current_price = bitvavo.get_ticker_price(market) or df.iloc[-1]["close"]
                position_bal = balance_map.get(base_currency, {})
                position_value = position_bal.get("total", 0) * current_price

                # Available budget = min(EUR balance, remaining global budget)
                available_budget = min(eur_balance, settings.crypto_global_budget_eur)

                action = decide_crypto_action(
                    symbol=market,
                    composite_result=composite,
                    current_position_value_eur=position_value,
                    available_budget_eur=available_budget,
                    portfolio_value_eur=max(portfolio_value, 1.0),
                    current_price=current_price,
                )

                # 4. Execute
                if action:
                    if settings.crypto_live_mode:
                        trader = LiveTrader(db, bitvavo)
                        order = await trader.execute_action(action, current_price, portfolio_value)
                    else:
                        trader = PaperTrader(db)
                        order = await trader.execute_action(action, current_price, portfolio_value)

                    results["actions"].append({
                        "symbol": market,
                        "side": action.side,
                        "signal": composite.signal,
                        "score": composite.composite_score,
                        "order_id": order.id if order else None,
                    })
                else:
                    results["actions"].append({
                        "symbol": market,
                        "signal": composite.signal,
                        "score": composite.composite_score,
                        "action": "hold",
                    })

            except Exception as e:
                logger.exception("Error processing %s: %s", market, e)
                results["actions"].append({"symbol": market, "error": str(e)})

        # 5. Check trailing stops on existing positions
        try:
            if settings.crypto_live_mode:
                live_trader = LiveTrader(db, bitvavo)
                triggered = await live_trader.check_open_positions()
            else:
                paper_trader = PaperTrader(db)

                def get_price(symbol: str) -> float | None:
                    return bitvavo.get_ticker_price(symbol)

                triggered = await paper_trader.check_open_positions(get_price)

            if triggered:
                results["stops_triggered"] = triggered
                logger.info("Stops triggered: %d positions closed", len(triggered))
        except Exception as e:
            logger.exception("Error checking stops: %s", e)

        await db.commit()

    logger.info("═══ CRYPTO DAILY JOB END — %d actions ═══", len(results["actions"]))
    return results


# ── Weekly stocks/ETFs/bonds job ────────────────────────────────────────

async def run_stocks_weekly_job() -> dict[str, Any]:
    """Weekly stock/ETF/bond analysis and recommendation job.

    1. Sync positions from Ghostfolio
    2. Fetch FMP data (prices, fundamentals, dividends, news)
    3. Compute all three scores per asset
    4. Generate composite scores
    5. Call LLM for narrative synthesis
    6. Store recommendations
    """
    logger.info("═══ STOCKS WEEKLY JOB START ═══")
    results: dict[str, Any] = {"timestamp": datetime.utcnow().isoformat(), "recommendations": []}

    ghostfolio = GhostfolioClient()
    fmp = FMPClient()
    llm = get_llm_provider()

    system_prompt = (
        SYNTHESIS_SYSTEM_PROMPT_FR
        if settings.synthesis_language == "fr"
        else SYNTHESIS_SYSTEM_PROMPT_EN
    )

    async with async_session() as db:
        try:
            # 1. Sync positions from Ghostfolio
            holdings = await ghostfolio.get_holdings()
            logger.info("Fetched %d holdings from Ghostfolio", len(holdings))

            # Store positions
            for h in holdings:
                position = Position(**h)
                db.add(position)

            # Filter non-crypto positions
            non_crypto = [h for h in holdings if h["asset_type"] != AssetType.CRYPTO]

            # 2-5. Process each asset
            for holding in non_crypto:
                symbol = holding["symbol"]
                asset_type = holding["asset_type"]
                account_type = holding["account_type"]

                try:
                    logger.info("── Processing %s (%s) ──", symbol, asset_type.value)

                    # Fetch price history
                    from_date = date.today() - timedelta(days=365)
                    prices = await fmp.get_historical_prices(symbol, from_date=from_date)

                    if len(prices) < 20:
                        logger.warning("Not enough price data for %s (%d)", symbol, len(prices))
                        continue

                    # Convert to DataFrame
                    df = pd.DataFrame(prices)
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date").set_index("date")

                    # Ensure required columns
                    for col in ["open", "high", "low", "close", "volume"]:
                        if col not in df.columns:
                            df[col] = df.get("adjClose", df.get("close", 0))

                    # Technical analysis
                    regime = classify_volatility(df)
                    params = get_params(regime)
                    df = compute_indicators(df, params)
                    tech_score, tech_signals = score_technical(df)

                    # Fundamental analysis
                    is_etf = asset_type == AssetType.ETF
                    is_crypto = False
                    key_metrics = await fmp.get_key_metrics(symbol)
                    ratios = await fmp.get_financial_ratios(symbol)
                    news = await fmp.get_stock_news(symbol, limit=15)
                    etf_info = await fmp.get_etf_info(symbol) if is_etf else None

                    fund_score, fund_breakdown = score_fundamental(
                        key_metrics=key_metrics,
                        ratios=ratios,
                        news=news,
                        etf_info=etf_info,
                        is_etf=is_etf,
                        is_crypto=is_crypto,
                    )

                    # Dividend analysis
                    div_history = await fmp.get_dividend_history(symbol)
                    div_yield = None
                    payout_ratio = None
                    if key_metrics:
                        div_yield = key_metrics[0].get("dividendYield")
                        if div_yield:
                            div_yield = float(div_yield) * 100  # Convert to percentage
                    if ratios:
                        payout_ratio = ratios[0].get("payoutRatio")
                        if payout_ratio:
                            payout_ratio = float(payout_ratio) * 100

                    div_score, div_breakdown = score_dividend(
                        dividend_yield=div_yield,
                        dividend_history=div_history,
                        payout_ratio=payout_ratio,
                        is_bond=asset_type == AssetType.BOND,
                    )

                    # Composite
                    composite = compute_composite(
                        tech_score, fund_score, div_score,
                        asset_type=asset_type.value,
                    )

                    # Store score
                    score_record = Score(
                        symbol=symbol,
                        date=date.today(),
                        technical_score=tech_score,
                        fundamental_score=fund_score,
                        dividend_score=div_score,
                        composite_score=composite.composite_score,
                        weights_used=weights_to_json(composite.weights),
                        signal=composite.signal,
                    )
                    db.add(score_record)
                    await db.flush()  # Get the score_record.id

                    # LLM narrative synthesis
                    prompt = _build_synthesis_prompt(
                        symbol=symbol,
                        name=holding["name"],
                        asset_type=asset_type.value,
                        account_type=account_type.value,
                        technical_score=tech_score,
                        fundamental_score=fund_score,
                        dividend_score=div_score,
                        composite_score=composite.composite_score,
                        signal=composite.signal,
                        details={
                            "technical_signals": tech_signals.signals,
                            "fundamental": fund_breakdown.details,
                            "dividend": div_breakdown.details,
                        },
                    )

                    try:
                        narrative = await llm.generate(prompt, system_prompt=system_prompt)
                    except Exception as e:
                        logger.error("LLM synthesis failed for %s: %s", symbol, e)
                        narrative = f"[Synthesis unavailable: {e}]"

                    # Map signal to ActionType
                    action_map = {
                        "strong_buy": ActionType.STRONG_BUY,
                        "buy": ActionType.BUY,
                        "hold": ActionType.HOLD,
                        "reduce": ActionType.REDUCE,
                        "sell": ActionType.SELL,
                    }
                    action_type = action_map.get(composite.signal, ActionType.HOLD)

                    # Confidence from composite score (normalise to 0-1)
                    confidence = composite.composite_score / 100.0

                    # Store recommendation
                    recommendation = Recommendation(
                        symbol=symbol,
                        date=date.today(),
                        account_type=account_type.value,
                        action=action_type,
                        confidence=round(confidence, 3),
                        narrative=narrative,
                        score_id=score_record.id,
                    )
                    db.add(recommendation)

                    results["recommendations"].append({
                        "symbol": symbol,
                        "name": holding["name"],
                        "account_type": account_type.value,
                        "signal": composite.signal,
                        "composite_score": composite.composite_score,
                        "action": action_type.value,
                    })

                    logger.info(
                        "%s: composite=%.1f signal=%s",
                        symbol,
                        composite.composite_score,
                        composite.signal,
                    )

                except Exception as e:
                    logger.exception("Error processing %s: %s", symbol, e)
                    results["recommendations"].append({
                        "symbol": symbol,
                        "error": str(e),
                    })

        except Exception as e:
            logger.exception("Stocks weekly job error: %s", e)
            results["error"] = str(e)
        finally:
            await ghostfolio.close()
            await fmp.close()

        await db.commit()

    fmp.clear_cache()
    logger.info(
        "═══ STOCKS WEEKLY JOB END — %d recommendations ═══",
        len(results["recommendations"]),
    )
    return results
