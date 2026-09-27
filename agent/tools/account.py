"""Tool: get_account_balance — returns available USD (or other currency) balance."""
from __future__ import annotations

import structlog
from agents import RunContextWrapper, function_tool

from agent.coinbase.client import CoinbaseClient
from agent.context import AgentContext

logger = structlog.get_logger()


@function_tool
async def get_account_balance(
    ctx: RunContextWrapper[AgentContext],
    currency: str = "USD",
) -> str:
    """Get the available balance for a currency in the Coinbase account.

    Args:
        currency: Currency code, e.g. 'USD', 'BTC'. Defaults to 'USD'.

    Returns:
        A string with the available balance.
    """
    context = ctx.context
    client: CoinbaseClient = context.client  # type: ignore[assignment]

    with context.tracer.start_as_current_span("get_account_balance") as span:
        span.set_attribute("currency", currency)
        balance = await client.get_account_balance(currency)
        span.set_attribute("balance", balance)
        logger.info("balance_fetched", currency=currency, balance=balance)
        return f"Available {currency} balance: ${balance:,.2f}"
