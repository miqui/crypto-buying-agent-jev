"""Shared runtime context passed through the OpenAI Agents SDK RunContextWrapper."""
from __future__ import annotations

from dataclasses import dataclass, field

from opentelemetry import metrics, trace

from agent.core.config import Settings
from agent.state.tracker import SpendTracker


@dataclass
class AgentContext:
    """Everything the agent tools need at runtime.

    Passed as ``context=`` to ``Runner.run()``.  Tools access it via
    ``ctx.context`` where ``ctx`` is a ``RunContextWrapper[AgentContext]``.
    """

    settings: Settings
    tracker: SpendTracker
    client: object  # CoinbaseClient — typed as object to avoid circular import
    trigger_price: float = 0.0
    tracer: trace.Tracer = field(
        default_factory=lambda: trace.get_tracer("crypto-buying-agent"),
        repr=False,
        compare=False,
    )
    meter: metrics.Meter = field(
        default_factory=lambda: metrics.get_meter("crypto-buying-agent"),
        repr=False,
        compare=False,
    )
