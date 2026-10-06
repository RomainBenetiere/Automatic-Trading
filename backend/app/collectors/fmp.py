"""Financial Modeling Prep (FMP) API client — prices, fundamentals, dividends, news."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://financialmodelingprep.com/stable"


class FMPClient:
    """Client for the Financial Modeling Prep REST API.

    Handles authentication, rate-limit awareness, and in-memory caching
    for the duration of a single analysis run.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.fmp_api_key
        self._client = httpx.AsyncClient(timeout=30.0)
        self._cache: dict[str, Any] = {}
        self._request_count = 0

    # ── Internal helpers ────────────────────────────────────────────────

    async def _get(self, endpoint: str, params: dict | None = None) -> Any:
        """Make an authenticated GET request with caching."""
        params = params or {}
        params["apikey"] = self.api_key

        cache_key = f"{endpoint}:{sorted(params.items())}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        url = f"{BASE_URL}/{endpoint.lstrip('/')}"
        self._request_count += 1
        logger.debug("FMP request #%d: %s", self._request_count, url)

        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        self._cache[cache_key] = data
        return data

    def clear_cache(self) -> None:
        """Clear the in-memory response cache (call between analysis runs)."""
        self._cache.clear()
        self._request_count = 0

    # ── Price data ──────────────────────────────────────────────────────

    async def get_historical_prices(
        self,
        symbol: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch daily OHLCV price history for a symbol.

        Returns list of dicts with keys: date, open, high, low, close, volume.
        """
        params: dict[str, str] = {"symbol": symbol}
        if from_date:
            params["from"] = from_date.isoformat()
        if to_date:
            params["to"] = to_date.isoformat()

        data = await self._get("historical-price-eod/full", params)

        # FMP returns {historical: [...]} or a flat list
        if isinstance(data, dict):
            prices = data.get("historical", [])
        elif isinstance(data, list):
            prices = data
        else:
            prices = []

        logger.info("FMP: fetched %d price records for %s", len(prices), symbol)
        return prices

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch real-time quote for a symbol."""
        data = await self._get("quote", {"symbol": symbol})
        if isinstance(data, list) and data:
            return data[0]
        return data if isinstance(data, dict) else {}

    # ── Fundamentals ────────────────────────────────────────────────────

    async def get_key_metrics(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch pre-computed valuation metrics (P/E, P/B, EV/EBITDA, etc.)."""
        data = await self._get("key-metrics", {"symbol": symbol})
        return data if isinstance(data, list) else [data] if data else []

    async def get_financial_ratios(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch financial ratios (payout ratio, growth rates, margins)."""
        data = await self._get("ratios", {"symbol": symbol})
        return data if isinstance(data, list) else [data] if data else []

    async def get_income_statement(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch income statement data."""
        data = await self._get("income-statement", {"symbol": symbol})
        return data if isinstance(data, list) else [data] if data else []

    async def get_balance_sheet(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch balance sheet data."""
        data = await self._get("balance-sheet-statement", {"symbol": symbol})
        return data if isinstance(data, list) else [data] if data else []

    async def get_company_profile(self, symbol: str) -> dict[str, Any]:
        """Fetch company profile (sector, industry, description, etc.)."""
        data = await self._get("profile", {"symbol": symbol})
        if isinstance(data, list) and data:
            return data[0]
        return data if isinstance(data, dict) else {}

    # ── ETF-specific ────────────────────────────────────────────────────

    async def get_etf_info(self, symbol: str) -> dict[str, Any]:
        """Fetch ETF information (expense ratio, AUM, etc.)."""
        data = await self._get("etf-info", {"symbol": symbol})
        if isinstance(data, list) and data:
            return data[0]
        return data if isinstance(data, dict) else {}

    # ── Dividends ───────────────────────────────────────────────────────

    async def get_dividend_history(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch historical dividend payments for a symbol.

        Returns list of dicts with keys: date, dividend, adjDividend, etc.
        """
        data = await self._get("dividends", {"symbol": symbol})
        dividends = data if isinstance(data, list) else []
        logger.info("FMP: fetched %d dividend records for %s", len(dividends), symbol)
        return dividends

    async def get_dividend_calendar(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch market-wide dividend calendar."""
        params: dict[str, str] = {}
        if from_date:
            params["from"] = from_date.isoformat()
        if to_date:
            params["to"] = to_date.isoformat()
        data = await self._get("dividends-calendar", params)
        return data if isinstance(data, list) else []

    # ── News ────────────────────────────────────────────────────────────

    async def get_stock_news(
        self, symbol: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Fetch recent news articles for a symbol."""
        data = await self._get(
            "stock-news", {"tickers": symbol, "limit": str(limit)}
        )
        news = data if isinstance(data, list) else []
        logger.info("FMP: fetched %d news articles for %s", len(news), symbol)
        return news

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Check if FMP API is reachable and the key is valid."""
        try:
            data = await self._get("quote", {"symbol": "AAPL"})
            return bool(data)
        except Exception:
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
