"""Tool: place_buy_order — executes a market buy with full guardrail enforcement."""
from __future__ import annotations

import asyncio

import structlog
from agents import RunContextWrapper, function_tool
from opentelemetry.trace import StatusCode
from rich.prompt import Confirm

from agent.coinbase.client import CoinbaseClient
from agent.context import AgentContext
from agent.notifications.email import notify_buy_executed, notify_guardrail_tripped

logger = structlog.get_logger()


@function_tool
async def place_buy_order(
    ctx: RunContextWrapper[AgentContext],
    amount_usd: float,
) -> str:
    """Place a market buy order on Coinbase for the configured coin.

    Performs all safety checks before executing:
    - Amount is within configured min/max limits
    - Daily and lifetime spend caps are not exceeded
    - Hourly buy rate limit is not exceeded
    - Available USD balance is sufficient
    - Current price has not drifted more than the configured threshold
      from the trigger price

    In dry-run mode the order is logged but never submitted.
    If require_approval is enabled the user is prompted for confirmation.

    Args:
        amount_usd: USD amount to spend on this buy.

    Returns:
        A string describing the outcome (success or reason for rejection).
    """
    context = ctx.context
    s = context.settings
    t = context.tracker
    client: CoinbaseClient = context.client  # type: ignore[assignment]
    coin = s.coin

    with context.tracer.start_as_current_span("place_buy_order") as span:
        span.set_attribute("coin", coin)
        span.set_attribute("requested_amount_usd", amount_usd)

        # ── 1. Guardrail: spend limits ─────────────────────────────────────
        ok, reason = t.can_buy(
            amount_usd,
            min_single=s.min_buy_usd,
            max_single=s.max_buy_usd,
            max_daily=s.max_daily_spend_usd,
            max_total=s.max_total_spend_usd,
            max_per_hour=s.max_buys_per_hour,
        )
        if not ok:
            span.set_attribute("blocked_reason", reason)
            span.set_status(StatusCode.ERROR, reason)
            logger.warning("buy_blocked_guardrail", reason=reason, amount_usd=amount_usd)
            _increment_counter(context, "buy_blocked_total", coin=coin)
            notify_guardrail_tripped(s, coin=coin, amount_usd=amount_usd, reason=reason)
            return f"Buy blocked by guardrail: {reason}"

        # ── 2. Guardrail: balance check ───────────────────────────────────
        usd_balance = await client.get_account_balance("USD")
        if usd_balance < amount_usd:
            reason = (
                f"Insufficient USD balance: ${usd_balance:,.2f} available, "
                f"${amount_usd:.2f} required"
            )
            span.set_attribute("blocked_reason", reason)
            span.set_status(StatusCode.ERROR, reason)
            logger.warning("buy_blocked_balance", reason=reason)
            _increment_counter(context, "buy_blocked_total", coin=coin)
            notify_guardrail_tripped(s, coin=coin, amount_usd=amount_usd, reason=reason)
            return f"Buy blocked: {reason}"

        # ── 3. Guardrail: price drift check ──────────────────────────────
        if context.trigger_price > 0:
            ticker = await client.get_ticker(coin)
            current_price = ticker.price_float
            drift_pct = abs(current_price - context.trigger_price) / context.trigger_price * 100
            span.set_attribute("current_price_usd", current_price)
            span.set_attribute("trigger_price_usd", context.trigger_price)
            span.set_attribute("price_drift_pct", drift_pct)
            if drift_pct > s.max_price_drift_pct:
                reason = (
                    f"Price drifted {drift_pct:.2f}% from trigger "
                    f"(max allowed: {s.max_price_drift_pct:.1f}%)"
                )
                span.set_status(StatusCode.ERROR, reason)
                logger.warning("buy_blocked_drift", reason=reason, drift_pct=drift_pct)
                _increment_counter(context, "buy_blocked_total", coin=coin)
                notify_guardrail_tripped(s, coin=coin, amount_usd=amount_usd, reason=reason)
                return f"Buy blocked: {reason}"

        # ── 4. Human approval (optional) ──────────────────────────────────
        if s.require_approval:
            loop = asyncio.get_event_loop()
            approved: bool = await loop.run_in_executor(
                None,
                lambda: Confirm.ask(
                    f"\n[bold yellow]Agent wants to buy ${amount_usd:.2f} of {coin}.[/bold yellow]\n"
                    f"Approve?",
                    default=False,
                ),
            )
            if not approved:
                reason = "rejected by user at approval prompt"
                span.set_attribute("blocked_reason", reason)
                logger.info("buy_rejected_by_user", amount_usd=amount_usd, coin=coin)
                return f"Buy of ${amount_usd:.2f} {reason}."

        # ── 5. Dry-run mode ───────────────────────────────────────────────
        if s.dry_run:
            logger.info(
                "buy_dry_run",
                coin=coin,
                amount_usd=amount_usd,
                message="DRY RUN — order not submitted",
            )
            span.set_attribute("dry_run", True)
            return (
                f"DRY RUN: would buy ${amount_usd:.2f} of {coin}. "
                "No order was submitted."
            )

        # ── 6. Execute ────────────────────────────────────────────────────
        order = await client.place_market_buy(coin, amount_usd)
        t.record_buy(amount_usd)

        span.set_attribute("order_id", order.id)
        span.set_attribute("order_status", order.status)
        _increment_counter(context, "buy_executed_total", coin=coin)
        _record_histogram(context, "buy_amount_usd", amount_usd, coin=coin)

        logger.info(
            "buy_executed",
            order_id=order.id,
            coin=coin,
            amount_usd=amount_usd,
            status=order.status,
        )
        notify_buy_executed(
            s,
            coin=coin,
            amount_usd=amount_usd,
            order_id=order.id,
            status=order.status,
        )

        return (
            f"Buy order placed successfully. "
            f"Order ID: {order.id}, status: {order.status}, "
            f"amount: ${amount_usd:.2f} of {coin}."
        )


# ── OTEL helpers ──────────────────────────────────────────────────────────────

def _increment_counter(context: AgentContext, name: str, *, coin: str) -> None:
    counter = context.meter.create_counter(name)
    counter.add(1, {"coin": coin})


def _record_histogram(
    context: AgentContext, name: str, value: float, *, coin: str
) -> None:
    hist = context.meter.create_histogram(name, unit="USD")
    hist.record(value, {"coin": coin})
