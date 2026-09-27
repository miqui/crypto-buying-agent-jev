"""Execution agent definition — the OpenAI Agents SDK is used ONLY as the
tool/execution layer here. The buy decision itself (action, amount, conviction)
is pre-computed by the Jev decision layer (agent/jev/*) before this agent ever
runs. The agent's job is narrow and fixed: confirm price, confirm balance, and
execute the pre-computed order via place_buy_order — it does not choose
whether or how much to buy.
"""
from __future__ import annotations

from agents import Agent

from agent.context import AgentContext
from agent.core.config import Settings
from agent.guardrails.buying import spending_limit_guardrail
from agent.tools.account import get_account_balance
from agent.tools.orders import place_buy_order
from agent.tools.price import get_current_price

_INSTRUCTIONS_TEMPLATE = """\
You are the execution layer for a crypto buying system. A decision has ALREADY
been made outside of you by the Jev decision model: buy ${amount_usd:.2f} of
{coin}. You do not decide whether to buy or how much — that decision is fixed.
Your sole job is to execute it safely. Follow this workflow exactly:

1. Call get_current_price to confirm the live price has not moved unreasonably.
2. Call get_account_balance to confirm sufficient USD funds are still available.
3. Call place_buy_order with amount_usd={amount_usd:.2f} EXACTLY — do not
   change this amount for any reason.
4. Report back clearly: what was executed and the outcome.

If any tool call fails or returns an error (including a guardrail rejection
inside place_buy_order), stop and report the error — do not retry, do not
substitute a different amount, and do not attempt workarounds. Safety first.

Guardrail note: spend limits, balance checks, and price-drift checks are all
enforced inside place_buy_order. You do not need to re-implement them — just
pass the fixed amount through and let the tool handle the rest.
"""


def build_execution_agent(settings: Settings, amount_usd: float) -> Agent[AgentContext]:
    """Return a configured execution agent for a single pre-computed order.

    Unlike a general-purpose buying agent, this agent is built fresh for each
    triggered decision so its fixed instructions embed the exact amount Jev
    (via agent/jev/compose.py) already decided on.
    """
    instructions = _INSTRUCTIONS_TEMPLATE.format(
        coin=settings.coin,
        amount_usd=amount_usd,
    )
    return Agent(
        name="CryptoExecutionAgent",
        model=settings.openai_model,
        instructions=instructions,
        tools=[get_current_price, get_account_balance, place_buy_order],
        input_guardrails=[spending_limit_guardrail],
    )
