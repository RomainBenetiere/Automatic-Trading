"""Yahoo Finance client (via ``yfinance``) — free, worldwide coverage.

Drop-in replacement for :class:`app.collectors.fmp.FMPClient`: every public
method returns data shaped like the FMP payloads that the analysis modules
already consume (``peRatio``, ``operatingProfitMargin``, ``dividend``…), so
``fundamental.py`` / ``dividend.py`` need no changes.

European tickers use Yahoo suffixes (``AI.PA`` Paris, ``ASML.AS`` Amsterdam,
``SAP.DE`` Xetra, ``CW8.PA``…). Ghostfolio symbols whose data source is
YAHOO already follow this convention. Others can be remapped with the
``YAHOO_SYMBOL_MAP`` setting, and bare ISINs are resolved automatically.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def _num(value: Any) -> float | None:
    """Coerce to float, mapping NaN / None / junk to None."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _parse_symbol_map(raw: str) -> dict[str, str]:
    """Parse ``"CW8=CW8.PA,FR0010315770=CW8.PA"`` into a dict."""
    mapping: dict[str, str] = {}
    for pair in (raw or "").split(","):
        if "=" in pair:
            src, dst = pair.split("=", 1)
            if src.strip() and dst.strip():
                mapping[src.strip().upper()] = dst.strip()
    return mapping


class YahooFinanceClient:
    """Async wrapper around ``yfinance`` exposing the FMPClient interface."""

    def __init__(self) -> None:
        import yfinance as yf  # imported lazily so tests don't need network

        self._yf = yf
        self._symbol_map = _parse_symbol_map(settings.yahoo_symbol_map)
        self._resolved: dict[str, str] = {}
        self._tickers: dict[str, Any] = {}
        self._info: dict[str, dict[str, Any]] = {}
        self._request_count = 0
        self.last_error: str | None = None

    # ── Internal helpers ────────────────────────────────────────────────

    async def _run(self, fn, *args, timeout: float = 30.0, **kwargs):
        """Run a blocking yfinance call in a worker thread, bounded by ``timeout``.

        Yahoo endpoints occasionally hang (seen with news); a timeout turns that
        into a regular exception that callers already handle.
        """
        self._request_count += 1
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout)

    async def _resolve(self, symbol: str) -> str:
        """Map a portfolio symbol to a Yahoo ticker (override map → ISIN search)."""
        key = symbol.upper()
        if key in self._resolved:
            return self._resolved[key]

        resolved = self._symbol_map.get(key, symbol)
        if resolved == symbol and ISIN_RE.match(key):
            try:
                search = await self._run(self._yf.Search, key, max_results=1, news_count=0)
                quotes = getattr(search, "quotes", None) or []
                if quotes and quotes[0].get("symbol"):
                    resolved = quotes[0]["symbol"]
                    logger.info("Yahoo: resolved ISIN %s → %s", key, resolved)
            except Exception as e:  # noqa: BLE001
                logger.warning("Yahoo: ISIN lookup failed for %s: %s", key, e)

        self._resolved[key] = resolved
        return resolved

    async def _ticker(self, symbol: str):
        yahoo_symbol = await self._resolve(symbol)
        if yahoo_symbol not in self._tickers:
            self._tickers[yahoo_symbol] = self._yf.Ticker(yahoo_symbol)
        return self._tickers[yahoo_symbol]

    async def _get_info(self, symbol: str) -> dict[str, Any]:
        """Fetch (and cache) ``Ticker.info`` — one HTTP call reused by several methods."""
        yahoo_symbol = await self._resolve(symbol)
        if yahoo_symbol not in self._info:
            ticker = await self._ticker(symbol)
            try:
                info = await self._run(lambda: ticker.info)
            except Exception as e:  # noqa: BLE001
                logger.warning("Yahoo: info unavailable for %s: %s", yahoo_symbol, e)
                info = {}
            self._info[yahoo_symbol] = info or {}
        return self._info[yahoo_symbol]

    def clear_cache(self) -> None:
        """Clear the in-memory caches (call between analysis runs)."""
        self._tickers.clear()
        self._info.clear()
        self._request_count = 0

    # ── Price data ──────────────────────────────────────────────────────

    async def get_historical_prices(
        self,
        symbol: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Daily OHLCV history (split/dividend-adjusted), newest first like FMP."""
        ticker = await self._ticker(symbol)
        start = from_date or (date.today() - timedelta(days=365))
        end = (to_date or date.today()) + timedelta(days=1)  # yfinance end is exclusive
        try:
            df = await self._run(
                ticker.history, start=start.isoformat(), end=end.isoformat(),
                interval="1d", auto_adjust=True, actions=False,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Yahoo: price history failed for %s: %s", symbol, e)
            return []

        prices: list[dict[str, Any]] = []
        if df is not None and not df.empty:
            for idx, row in df.iterrows():
                close = _num(row.get("Close"))
                if close is None:
                    continue
                prices.append({
                    "date": idx.date().isoformat(),
                    "open": _num(row.get("Open")) or close,
                    "high": _num(row.get("High")) or close,
                    "low": _num(row.get("Low")) or close,
                    "close": close,
                    "volume": _num(row.get("Volume")) or 0.0,
                })
        prices.reverse()
        logger.info("Yahoo: fetched %d price records for %s", len(prices), symbol)
        return prices

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        """Latest quote (price, change, volume, market cap)."""
        info = await self._get_info(symbol)
        price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
        return {
            "symbol": symbol,
            "price": price,
            "changesPercentage": _num(info.get("regularMarketChangePercent")),
            "volume": _num(info.get("regularMarketVolume")),
            "marketCap": _num(info.get("marketCap")),
            "currency": info.get("currency"),
        } if price is not None else {}

    # ── Fundamentals ────────────────────────────────────────────────────

    async def _annual_growth(self, symbol: str) -> list[dict[str, float]]:
        """YoY net-income & revenue growth (fractions) from annual income statements."""
        ticker = await self._ticker(symbol)
        try:
            stmt = await self._run(lambda: ticker.income_stmt)
        except Exception:  # noqa: BLE001
            return []
        if stmt is None or stmt.empty:
            return []

        stmt = stmt.reindex(sorted(stmt.columns, reverse=True), axis=1)  # newest first

        def row(*names: str) -> pd.Series | None:
            for n in names:
                if n in stmt.index:
                    return stmt.loc[n]
            return None

        net_income = row("Net Income", "Net Income Common Stockholders")
        revenue = row("Total Revenue", "Operating Revenue")
        periods: list[dict[str, float]] = []
        for i in range(min(4, len(stmt.columns) - 1)):
            period: dict[str, float] = {}
            for key, series in (("netIncomePerShareGrowth", net_income), ("revenueGrowth", revenue)):
                if series is None:
                    continue
                cur, prev = _num(series.iloc[i]), _num(series.iloc[i + 1])
                if cur is not None and prev not in (None, 0):
                    period[key] = (cur - prev) / abs(prev)
            if period:
                periods.append(period)
        return periods

    async def get_key_metrics(self, symbol: str) -> list[dict[str, Any]]:
        """Valuation metrics, newest period first (FMP ``key-metrics`` shape)."""
        info = await self._get_info(symbol)
        if not info:
            return []

        price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
        div_yield = _num(info.get("trailingAnnualDividendYield"))  # fraction
        if div_yield is None:
            rate = _num(info.get("dividendRate"))
            if rate is not None and price:
                div_yield = rate / price

        latest: dict[str, Any] = {
            "peRatio": _num(info.get("trailingPE")) or _num(info.get("forwardPE")),
            "pbRatio": _num(info.get("priceToBook")),
            "enterpriseValueOverEBITDA": _num(info.get("enterpriseToEbitda")),
            "marketCap": _num(info.get("marketCap")),
            "dividendYield": div_yield,
        }

        growth = await self._annual_growth(symbol)
        if growth:
            latest.update(growth[0])
            return [latest, *growth[1:]]

        # Fallback: Yahoo's own most-recent YoY growth figures
        if _num(info.get("earningsGrowth")) is not None:
            latest["netIncomePerShareGrowth"] = _num(info.get("earningsGrowth"))
        elif _num(info.get("revenueGrowth")) is not None:
            latest["revenueGrowth"] = _num(info.get("revenueGrowth"))
        return [latest]

    async def get_financial_ratios(self, symbol: str) -> list[dict[str, Any]]:
        """Quality ratios (FMP ``ratios`` shape — fractions, D/E as a ratio)."""
        info = await self._get_info(symbol)
        if not info:
            return []
        debt_eq = _num(info.get("debtToEquity"))  # Yahoo reports D/E in percent
        return [{
            "operatingProfitMargin": _num(info.get("operatingMargins")),
            "netProfitMargin": _num(info.get("profitMargins")),
            "debtEquityRatio": debt_eq / 100 if debt_eq is not None else None,
            "payoutRatio": _num(info.get("payoutRatio")),
            "returnOnEquity": _num(info.get("returnOnEquity")),
        }]

    async def get_income_statement(self, symbol: str) -> list[dict[str, Any]]:
        """Annual income statements, newest first."""
        ticker = await self._ticker(symbol)
        try:
            stmt = await self._run(lambda: ticker.income_stmt)
        except Exception:  # noqa: BLE001
            return []
        return self._statement_to_records(stmt)

    async def get_balance_sheet(self, symbol: str) -> list[dict[str, Any]]:
        """Annual balance sheets, newest first."""
        ticker = await self._ticker(symbol)
        try:
            stmt = await self._run(lambda: ticker.balance_sheet)
        except Exception:  # noqa: BLE001
            return []
        return self._statement_to_records(stmt)

    @staticmethod
    def _statement_to_records(stmt: pd.DataFrame | None) -> list[dict[str, Any]]:
        if stmt is None or stmt.empty:
            return []
        records = []
        for col in sorted(stmt.columns, reverse=True):
            rec = {"date": pd.Timestamp(col).date().isoformat()}
            rec.update({str(k): _num(v) for k, v in stmt[col].items()})
            records.append(rec)
        return records

    async def get_company_profile(self, symbol: str) -> dict[str, Any]:
        """Company profile (sector, industry, currency, description)."""
        info = await self._get_info(symbol)
        if not info:
            return {}
        return {
            "symbol": symbol,
            "companyName": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "currency": info.get("currency"),
            "exchange": info.get("exchange"),
            "description": info.get("longBusinessSummary"),
            "quoteType": info.get("quoteType"),
        }

    # ── ETF-specific ────────────────────────────────────────────────────

    async def get_etf_info(self, symbol: str) -> dict[str, Any]:
        """ETF info — ``expenseRatio`` as a fraction (0.0012 = 0.12 %), ``aum``."""
        info = await self._get_info(symbol)
        if not info:
            return {}
        expense = _num(info.get("annualReportExpenseRatio"))  # already a fraction
        if expense is None and _num(info.get("netExpenseRatio")) is not None:
            expense = _num(info.get("netExpenseRatio")) / 100  # reported in percent
        return {
            "symbol": symbol,
            "name": info.get("longName") or info.get("shortName"),
            "expenseRatio": expense,
            "aum": _num(info.get("totalAssets")),
            "category": info.get("category"),
            "currency": info.get("currency"),
        }

    # ── Dividends ───────────────────────────────────────────────────────

    async def get_dividend_history(self, symbol: str) -> list[dict[str, Any]]:
        """Dividend payments, newest first: ``[{date, dividend, adjDividend}]``."""
        ticker = await self._ticker(symbol)
        try:
            series = await self._run(lambda: ticker.dividends)
        except Exception as e:  # noqa: BLE001
            logger.warning("Yahoo: dividends failed for %s: %s", symbol, e)
            return []
        dividends = []
        if series is not None and not series.empty:
            for idx, amount in series.sort_index(ascending=False).items():
                amt = _num(amount)
                if amt:
                    d = pd.Timestamp(idx).date().isoformat()
                    dividends.append({"date": d, "dividend": amt, "adjDividend": amt})
        logger.info("Yahoo: fetched %d dividend records for %s", len(dividends), symbol)
        return dividends

    async def get_dividend_calendar(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Not available market-wide on Yahoo — kept for interface parity."""
        return []

    # ── News ────────────────────────────────────────────────────────────

    async def get_stock_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        """Recent news normalised to FMP keys: title, text, url, site, publishedDate."""
        ticker = await self._ticker(symbol)
        try:
            raw = await self._run(lambda: ticker.news, timeout=15.0) or []
        except Exception as e:  # noqa: BLE001
            logger.warning("Yahoo: news failed for %s: %s", symbol, e)
            return []

        news = []
        for item in raw[:limit]:
            c = item.get("content") if isinstance(item.get("content"), dict) else item
            ts = c.get("pubDate") or c.get("providerPublishTime")
            if isinstance(ts, (int, float)):
                ts = datetime.utcfromtimestamp(ts).isoformat()
            url = (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link")
            provider = c.get("provider")
            news.append({
                "title": c.get("title") or "",
                "text": c.get("summary") or c.get("description") or "",
                "url": url,
                "site": provider.get("displayName") if isinstance(provider, dict) else c.get("publisher"),
                "publishedDate": ts,
            })
        logger.info("Yahoo: fetched %d news articles for %s", len(news), symbol)
        return news

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Check Yahoo Finance is reachable (fetches a few days of a Paris ticker)."""
        self.last_error = None
        try:
            prices = await self.get_historical_prices(
                "AI.PA", from_date=date.today() - timedelta(days=10)
            )
            if not prices:
                self.last_error = "Empty response from Yahoo Finance (rate-limited or blocked?)"
            return bool(prices)
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            return False

    async def close(self) -> None:
        """No persistent connection to close (kept for interface parity)."""
        return None


def get_market_data_client():
    """Return the configured market-data client (``MARKET_DATA_PROVIDER``)."""
    provider = (settings.market_data_provider or "yahoo").lower()
    if provider == "fmp":
        from app.collectors.fmp import FMPClient
        return FMPClient()
    return YahooFinanceClient()
