"""Async Coinbase Exchange REST API client."""
from __future__ import annotations

import json

import httpx
import structlog

from agent.coinbase.auth import build_auth_headers
from agent.coinbase.models import Account, Order, Ticker
from agent.core.config import Settings

logger = structlog.get_logger()

_PRODUCTION_BASE = "https://api.exchange.coinbase.com"
_SANDBOX_BASE = "https://api-sandbox.exchange.coinbase.com"


class CoinbaseError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CoinbaseAuthError(CoinbaseError):
    """401 / 403 from Coinbase — bad key, secret, or passphrase."""


class CoinbaseInsufficientFundsError(CoinbaseError):
    """Insufficient funds to place the order."""


class CoinbaseClient:
    """Thin async wrapper around the Coinbase Exchange REST API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = _SANDBOX_BASE if settings.use_sandbox else _PRODUCTION_BASE
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(10.0),
            headers={"User-Agent": "crypto-buying-agent/0.1.0"},
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> CoinbaseClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ── Public helpers ────────────────────────────────────────────────────────

    def _auth(self, method: str, path: str, body: str = "") -> dict[str, str]:
        return build_auth_headers(
            api_key=self._settings.coinbase_api_key,
            secret_b64=self._settings.coinbase_api_secret,
            passphrase=self._settings.coinbase_api_passphrase,
            method=method,
            path=path,
            body=body,
        )

    # ── API methods ───────────────────────────────────────────────────────────

    async def get_ticker(self, product_id: str) -> Ticker:
        """Fetch the latest ticker for a product (e.g. BTC-USD)."""
        path = f"/products/{product_id}/ticker"
        resp = await self._http.get(path, headers=self._auth("GET", path))
        self._raise_for_status(resp, "get_ticker")
        return Ticker.model_validate(resp.json())

    async def get_accounts(self) -> list[Account]:
        """Return all accounts for the authenticated profile."""
        path = "/accounts"
        resp = await self._http.get(path, headers=self._auth("GET", path))
        self._raise_for_status(resp, "get_accounts")
        return [Account.model_validate(a) for a in resp.json()]

    async def get_account_balance(self, currency: str) -> float:
        """Return available balance for the given currency (e.g. 'USD')."""
        accounts = await self.get_accounts()
        for acct in accounts:
            if acct.currency.upper() == currency.upper():
                return acct.available_float
        return 0.0

    async def place_market_buy(self, product_id: str, funds_usd: float) -> Order:
        """Place a market buy order spending exactly ``funds_usd`` USD."""
        path = "/orders"
        payload = {
            "type": "market",
            "side": "buy",
            "product_id": product_id,
            "funds": f"{funds_usd:.2f}",
        }
        body = json.dumps(payload)
        resp = await self._http.post(
            path,
            headers=self._auth("POST", path, body),
            content=body,
        )
        self._raise_for_status(resp, "place_market_buy")
        return Order.model_validate(resp.json())

    # ── Error handling ────────────────────────────────────────────────────────

    def _raise_for_status(self, resp: httpx.Response, operation: str) -> None:
        if resp.status_code in (200, 201):
            return

        detail = resp.text
        try:
            body = resp.json()
            detail = body.get("message", resp.text)
        except Exception:
            pass

        msg = f"{operation} failed [{resp.status_code}]: {detail}"
        logger.error(
            "coinbase_api_error",
            operation=operation,
            status_code=resp.status_code,
            detail=detail,
        )

        if resp.status_code in (401, 403):
            raise CoinbaseAuthError(msg, resp.status_code)
        if resp.status_code == 400 and "insufficient" in detail.lower():
            raise CoinbaseInsufficientFundsError(msg, resp.status_code)
        raise CoinbaseError(msg, resp.status_code)
