"""Tool: get_current_price — fetches the latest market price from Coinbase."""
from __future__ import annotations

import structlog
from agents import RunContextWrapper, function_tool

from agent.coinbase.client import CoinbaseClient
from agent.context import AgentContext

logger = structlog.get_logger()


@function_tool
async def get_current_price(ctx: RunContextWrapper[AgentContext]) -> str:
    """Get the current market price of the configured crypto coin from Coinbase.

    Returns the latest trade price as a human-readable string.
    """
    context = ctx.context
    client: CoinbaseClient = context.client  # type: ignore[assignment]
    coin = context.settings.coin

    with context.tracer.start_as_current_span("get_current_price") as span:
        span.set_attribute("coin", coin)
        ticker = await client.get_ticker(coin)
        price = ticker.price_float
        span.set_attribute("price_usd", price)
        logger.info("price_fetched", coin=coin, price_usd=price)
        return f"Current price of {coin}: ${price:,.2f} USD"
