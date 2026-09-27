"""Input guardrail — blocks agent run when spend caps are already exceeded.

This is a fast pre-flight check before the LLM even starts.  The detailed
per-tool checks (balance, drift) happen inside place_buy_order itself.
"""
from __future__ import annotations

import structlog
from agents import Agent, GuardrailFunctionOutput, RunContextWrapper, input_guardrail

from agent.context import AgentContext

logger = structlog.get_logger()


@input_guardrail
async def spending_limit_guardrail(
    ctx: RunContextWrapper[AgentContext],
    agent: Agent[AgentContext],
    input: object,
) -> GuardrailFunctionOutput:
    """Reject agent invocation immediately if the minimum possible buy would
    already violate a daily, lifetime, or hourly cap.

    This avoids spending LLM tokens on a session that cannot result in a buy.
    """
    context = ctx.context
    s = context.settings
    t = context.tracker

    ok, reason = t.can_buy(
        s.min_buy_usd,
        min_single=s.min_buy_usd,
        max_single=s.max_buy_usd,
        max_daily=s.max_daily_spend_usd,
        max_total=s.max_total_spend_usd,
        max_per_hour=s.max_buys_per_hour,
    )

    if not ok:
        logger.warning("input_guardrail_tripped", reason=reason)
        return GuardrailFunctionOutput(tripwire_triggered=True, output_info=reason)

    return GuardrailFunctionOutput(tripwire_triggered=False, output_info="")
