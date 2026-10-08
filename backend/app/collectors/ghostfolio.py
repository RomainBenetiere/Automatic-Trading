"""Ghostfolio API client — fetches portfolio holdings, transactions, and dividends."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import httpx

from app.config import settings
from app.models.position import AccountType, AssetType

logger = logging.getLogger(__name__)

# Mapping from Ghostfolio account names to our AccountType enum.
# Users should adjust this mapping to match their Ghostfolio account naming.
ACCOUNT_TYPE_MAP: dict[str, AccountType] = {
    "brokerage": AccountType.BROKERAGE,
    "cto": AccountType.BROKERAGE,
    "pea": AccountType.PEA,
    "assurance vie": AccountType.ASSURANCE_VIE,
    "assurance_vie": AccountType.ASSURANCE_VIE,
    "av": AccountType.ASSURANCE_VIE,
    "per": AccountType.PER,
}

ASSET_TYPE_MAP: dict[str, AssetType] = {
    "EQUITY": AssetType.STOCK,
    "ETF": AssetType.ETF,
    "BOND": AssetType.BOND,
    "CRYPTOCURRENCY": AssetType.CRYPTO,
}


class GhostfolioClient:
    """Client for the Ghostfolio self-hosted REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        security_token: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ghostfolio_url).rstrip("/")
        self.security_token = security_token or settings.ghostfolio_token
        self._jwt_token: str | None = None
        self._client = httpx.AsyncClient(timeout=30.0)

    # ── Authentication ──────────────────────────────────────────────────

    async def _authenticate(self) -> None:
        """Obtain a JWT bearer token via the anonymous auth endpoint."""
        url = f"{self.base_url}/api/v1/auth/anonymous"
        resp = await self._client.post(
            url, json={"accessToken": self.security_token}
        )
        resp.raise_for_status()
        data = resp.json()
        self._jwt_token = data.get("authToken") or data.get("token")
        logger.info("Ghostfolio: authenticated successfully")

    async def _ensure_auth(self) -> None:
        """Ensure we have a valid JWT token, re-authenticating if needed."""
        if self._jwt_token is None:
            await self._authenticate()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._jwt_token}"}

    async def _get(self, path: str, params: dict | None = None) -> Any:
        """Authenticated GET request with auto-retry on 401."""
        await self._ensure_auth()
        url = f"{self.base_url}{path}"
        resp = await self._client.get(url, headers=self._headers(), params=params)
        if resp.status_code == 401:
            # Token expired — re-authenticate and retry once
            await self._authenticate()
            resp = await self._client.get(url, headers=self._headers(), params=params)
        resp.raise_for_status()
        return resp.json()

    # ── Portfolio data ──────────────────────────────────────────────────

    async def get_holdings(self) -> list[dict[str, Any]]:
        """Fetch current portfolio holdings per account.

        Returns a list of normalised holding dicts ready for Position model creation.
        """
        accounts = await self.get_accounts()
        holdings = []

        if not accounts:
            logger.warning("Ghostfolio: no accounts found. Falling back to global holdings.")
            accounts = [{"id": None, "name": "brokerage"}]

        for account in accounts:
            account_id = account.get("id")
            account_name = account.get("name", "brokerage")
            account_type = ACCOUNT_TYPE_MAP.get(
                str(account_name).lower(), AccountType.BROKERAGE
            )

            params = {"accounts": account_id} if account_id else None
            data = await self._get("/api/v1/portfolio/holdings", params=params)

            for item in data.get("holdings", data) if isinstance(data, dict) else data:
                symbol = item.get("symbol", "")
                if not symbol:
                    continue

                # Determine asset type (Ghostfolio may send null for either field)
                asset_class = (item.get("assetClass") or "").upper()
                asset_sub_class = (item.get("assetSubClass") or "").upper()
                if asset_sub_class == "CASH":
                    continue  # cash balances are not analysable assets
                if asset_sub_class == "ETF":
                    asset_type = AssetType.ETF
                elif asset_sub_class == "BOND" or asset_class == "FIXED_INCOME":
                    asset_type = AssetType.BOND
                elif "CRYPTOCURRENCY" in (asset_class, asset_sub_class):
                    asset_type = AssetType.CRYPTO
                else:
                    asset_type = ASSET_TYPE_MAP.get(asset_class, AssetType.STOCK)

                holdings.append(
                    {
                        "symbol": symbol,
                        "name": item.get("name", symbol),
                        "asset_type": asset_type,
                        "account_type": account_type,
                        "quantity": float(item.get("quantity") or 0),
                        "avg_cost": item.get("averagePrice"),
                        "current_price": item.get("marketPrice"),
                        "currency": item.get("currency", "EUR"),
                        "snapshot_date": date.today(),
                    }
                )

        logger.info("Ghostfolio: fetched %d holdings across %d accounts", len(holdings), len(accounts))
        return holdings

    async def get_accounts(self) -> list[dict[str, Any]]:
        """Fetch account list (id, name, balance, currency)."""
        data = await self._get("/api/v1/account")
        accounts = data.get("accounts", data) if isinstance(data, dict) else data
        return accounts

    async def get_activities(
        self, start_date: date | None = None, end_date: date | None = None
    ) -> list[dict[str, Any]]:
        """Fetch transaction activities (buys, sells, dividends)."""
        params: dict[str, str] = {}
        if start_date:
            params["startDate"] = start_date.isoformat()
        if end_date:
            params["endDate"] = end_date.isoformat()

        data = await self._get("/api/v1/order", params=params)
        activities = (
            data.get("activities", data) if isinstance(data, dict) else data
        )
        return activities

    async def get_performance(self, date_range: str = "max") -> dict[str, Any]:
        """Fetch portfolio performance summary."""
        data = await self._get(
            "/api/v1/portfolio/performance",
            params={"range": date_range},
        )
        return data

    async def get_dividends(self) -> list[dict[str, Any]]:
        """Fetch dividend activities from transaction history."""
        activities = await self.get_activities()
        dividends = [
            a for a in activities if a.get("type", "").upper() == "DIVIDEND"
        ]
        logger.info("Ghostfolio: found %d dividend transactions", len(dividends))
        return dividends

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Check that Ghostfolio is reachable AND the security token is valid."""
        try:
            await self._authenticate()
            return bool(self._jwt_token)
        except Exception:
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
