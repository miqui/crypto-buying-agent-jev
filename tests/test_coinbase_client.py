"""Tests for the Coinbase Exchange API client (mocked with respx)."""
from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from agent.coinbase.client import (
    CoinbaseAuthError,
    CoinbaseClient,
    CoinbaseError,
    CoinbaseInsufficientFundsError,
)
from agent.core.config import Settings


@pytest.fixture
def settings(base_env: None) -> Settings:  # noqa: ARG001
    from agent.core.config import get_settings

    return get_settings()


@pytest.fixture
def client(settings: Settings) -> CoinbaseClient:
    return CoinbaseClient(settings)


# ── get_ticker ────────────────────────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_get_ticker_returns_ticker(client: CoinbaseClient) -> None:
    respx.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker").mock(
        return_value=Response(
            200,
            json={"price": "62500.00", "bid": "62499.00", "ask": "62501.00", "volume": "1000"},
        )
    )
    ticker = await client.get_ticker("BTC-USD")
    assert ticker.price_float == pytest.approx(62500.0)


@respx.mock
@pytest.mark.asyncio
async def test_get_ticker_raises_on_401(client: CoinbaseClient) -> None:
    respx.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker").mock(
        return_value=Response(401, json={"message": "Unauthorized"})
    )
    with pytest.raises(CoinbaseAuthError):
        await client.get_ticker("BTC-USD")


@respx.mock
@pytest.mark.asyncio
async def test_get_ticker_raises_on_500(client: CoinbaseClient) -> None:
    respx.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker").mock(
        return_value=Response(500, text="Internal Server Error")
    )
    with pytest.raises(CoinbaseError):
        await client.get_ticker("BTC-USD")


# ── get_account_balance ───────────────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_get_account_balance_usd(client: CoinbaseClient) -> None:
    respx.get("https://api.exchange.coinbase.com/accounts").mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": "abc",
                    "currency": "USD",
                    "balance": "5000.00",
                    "available": "4800.00",
                    "hold": "200.00",
                },
                {
                    "id": "def",
                    "currency": "BTC",
                    "balance": "0.5",
                    "available": "0.5",
                    "hold": "0",
                },
            ],
        )
    )
    balance = await client.get_account_balance("USD")
    assert balance == pytest.approx(4800.0)


@respx.mock
@pytest.mark.asyncio
async def test_get_account_balance_missing_currency(client: CoinbaseClient) -> None:
    respx.get("https://api.exchange.coinbase.com/accounts").mock(
        return_value=Response(200, json=[])
    )
    balance = await client.get_account_balance("USD")
    assert balance == 0.0


# ── place_market_buy ──────────────────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_place_market_buy_success(client: CoinbaseClient) -> None:
    respx.post("https://api.exchange.coinbase.com/orders").mock(
        return_value=Response(
            201,
            json={
                "id": "order-123",
                "product_id": "BTC-USD",
                "side": "buy",
                "type": "market",
                "status": "pending",
                "funds": "100.00",
            },
        )
    )
    order = await client.place_market_buy("BTC-USD", 100.0)
    assert order.id == "order-123"
    assert order.status == "pending"


@respx.mock
@pytest.mark.asyncio
async def test_place_market_buy_insufficient_funds(client: CoinbaseClient) -> None:
    respx.post("https://api.exchange.coinbase.com/orders").mock(
        return_value=Response(400, json={"message": "Insufficient funds"})
    )
    with pytest.raises(CoinbaseInsufficientFundsError):
        await client.place_market_buy("BTC-USD", 100.0)


@respx.mock
@pytest.mark.asyncio
async def test_place_market_buy_sends_correct_payload(client: CoinbaseClient) -> None:
    captured: list[dict] = []

    def handler(request: object) -> Response:
        import httpx
        r: httpx.Request = request  # type: ignore[assignment]
        captured.append(json.loads(r.content))
        return Response(
            201,
            json={
                "id": "order-456",
                "product_id": "BTC-USD",
                "side": "buy",
                "type": "market",
                "status": "pending",
            },
        )

    respx.post("https://api.exchange.coinbase.com/orders").mock(side_effect=handler)
    await client.place_market_buy("BTC-USD", 250.0)
    assert captured[0]["type"] == "market"
    assert captured[0]["side"] == "buy"
    assert captured[0]["funds"] == "250.00"
