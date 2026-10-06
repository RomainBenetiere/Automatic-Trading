"""Bitvavo API client — crypto data retrieval and order execution."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from python_bitvavo_api.bitvavo import Bitvavo

from app.config import settings

logger = logging.getLogger(__name__)


class BitvavoClient:
    """Wrapper around the official Bitvavo Python SDK.

    Provides both data retrieval and order execution methods.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.bitvavo_api_key
        self.api_secret = api_secret or settings.bitvavo_api_secret
        self._bitvavo = Bitvavo(
            {
                "APIKEY": self.api_key,
                "APISECRET": self.api_secret,
                "RESTURL": "https://api.bitvavo.com/v2",
                "WSURL": "wss://ws.bitvavo.com/v2/",
                "ACCESSWINDOW": 10000,
                "DEBUGGING": False,
            }
        )

    # ── Data retrieval ──────────────────────────────────────────────────

    def get_balances(self) -> list[dict[str, Any]]:
        """Fetch current crypto balances.

        Returns list of dicts with keys: symbol, available, inOrder.
        """
        response = self._bitvavo.balance({})
        if isinstance(response, dict) and "error" in response:
            logger.error("Bitvavo balance error: %s", response)
            return []

        balances = []
        for item in response:
            available = float(item.get("available", 0))
            in_order = float(item.get("inOrder", 0))
            if available > 0 or in_order > 0:
                balances.append(
                    {
                        "symbol": item["symbol"],
                        "available": available,
                        "in_order": in_order,
                        "total": available + in_order,
                    }
                )

        logger.info("Bitvavo: fetched %d non-zero balances", len(balances))
        return balances

    def get_candles(
        self,
        market: str,
        interval: str = "1d",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV candle data for a market pair.

        Args:
            market: e.g. "BTC-EUR"
            interval: e.g. "1m", "5m", "1h", "4h", "1d"
            limit: number of candles to return

        Returns list of dicts with keys: timestamp, open, high, low, close, volume.
        """
        response = self._bitvavo.candles(
            market, interval, {"limit": limit}
        )
        if isinstance(response, dict) and "error" in response:
            logger.error("Bitvavo candles error for %s: %s", market, response)
            return []

        candles = []
        for c in response:
            # Bitvavo returns [timestamp, open, high, low, close, volume]
            if isinstance(c, list) and len(c) >= 6:
                candles.append(
                    {
                        "timestamp": int(c[0]),
                        "datetime": datetime.fromtimestamp(int(c[0]) / 1000),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                    }
                )

        # Sort chronologically (oldest first)
        candles.sort(key=lambda x: x["timestamp"])
        logger.info("Bitvavo: fetched %d candles for %s", len(candles), market)
        return candles

    def get_ticker_price(self, market: str) -> float | None:
        """Get the latest ticker price for a market pair."""
        response = self._bitvavo.tickerPrice({"market": market})
        if isinstance(response, dict) and "price" in response:
            return float(response["price"])
        if isinstance(response, list) and response:
            return float(response[0].get("price", 0))
        logger.warning("Bitvavo: could not get price for %s: %s", market, response)
        return None

    def get_ticker_24h(self, market: str) -> dict[str, Any]:
        """Get 24-hour ticker statistics."""
        response = self._bitvavo.ticker24h({"market": market})
        if isinstance(response, dict):
            return response
        if isinstance(response, list) and response:
            return response[0]
        return {}

    # ── Order execution ─────────────────────────────────────────────────

    def place_market_order(
        self,
        market: str,
        side: str,
        amount: float | None = None,
        quote_amount: float | None = None,
    ) -> dict[str, Any]:
        """Place a market order.

        Args:
            market: e.g. "BTC-EUR"
            side: "buy" or "sell"
            amount: quantity in base currency (e.g. BTC amount)
            quote_amount: amount in quote currency (e.g. EUR amount) — for buys

        Returns order result dict from Bitvavo.
        """
        body: dict[str, Any] = {
            "market": market,
            "side": side,
            "orderType": "market",
        }
        if amount is not None:
            body["amount"] = str(amount)
        elif quote_amount is not None:
            body["amountQuote"] = str(quote_amount)

        logger.info(
            "Bitvavo: placing market %s order on %s — %s",
            side,
            market,
            body,
        )
        response = self._bitvavo.placeOrder(
            market, side, "market", body
        )

        if isinstance(response, dict) and "error" in response:
            logger.error("Bitvavo order error: %s", response)
        else:
            logger.info("Bitvavo: order placed — %s", response)

        return response

    def place_limit_order(
        self,
        market: str,
        side: str,
        amount: float,
        price: float,
    ) -> dict[str, Any]:
        """Place a limit order.

        Args:
            market: e.g. "BTC-EUR"
            side: "buy" or "sell"
            amount: quantity in base currency
            price: limit price in quote currency

        Returns order result dict from Bitvavo.
        """
        body: dict[str, Any] = {
            "market": market,
            "side": side,
            "orderType": "limit",
            "amount": str(amount),
            "price": str(price),
        }

        logger.info(
            "Bitvavo: placing limit %s order on %s — %s",
            side,
            market,
            body,
        )
        response = self._bitvavo.placeOrder(
            market, side, "limit", body
        )

        if isinstance(response, dict) and "error" in response:
            logger.error("Bitvavo order error: %s", response)
        else:
            logger.info("Bitvavo: order placed — %s", response)

        return response

    def get_order_status(self, market: str, order_id: str) -> dict[str, Any]:
        """Check the status of an existing order."""
        response = self._bitvavo.getOrder(market, order_id)
        return response if isinstance(response, dict) else {}

    def cancel_order(self, market: str, order_id: str) -> dict[str, Any]:
        """Cancel an existing order."""
        logger.info("Bitvavo: cancelling order %s on %s", order_id, market)
        response = self._bitvavo.cancelOrder(market, order_id)
        return response if isinstance(response, dict) else {}

    def get_trades(self, market: str, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch recent trade history for a market."""
        response = self._bitvavo.trades(market, {"limit": limit})
        if isinstance(response, list):
            return response
        return []

    # ── Lifecycle ───────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Check if the Bitvavo API is reachable."""
        try:
            response = self._bitvavo.time()
            return isinstance(response, dict) and "time" in response
        except Exception:
            return False
