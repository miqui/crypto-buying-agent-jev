"""Price monitoring loop — polls Coinbase, computes a Jev decision, then hands
a fixed execution order to the OpenAI Agents SDK execution layer.

Flow per poll:
    price <= target?
        → build_state() with live price/balance/caps
        → DecisionProvider.decide() (Jev via OpenRouter, or dry-run)
        → compose_decision() (deterministic composition + caps/balance override)
        → action == "buy"  → build_execution_agent(amount) → Runner.run()
        → action == "wait" → log, keep polling
        → action == "review" → notify + log, NO order
"""
from __future__ import annotations

import asyncio
import traceback

import structlog
from agents import InputGuardrailTripwireTriggered, Runner
from opentelemetry import metrics, trace
from opentelemetry.trace import StatusCode
from rich.console import Console

from agent.agent import build_execution_agent
from agent.coinbase.client import CoinbaseClient, CoinbaseError
from agent.context import AgentContext
from agent.core.config import Settings
from agent.core.telemetry import get_meter, get_tracer
from agent.jev.compose import compose_decision
from agent.jev.providers import get_provider
from agent.jev.questions import build_questions, build_state
from agent.notifications.email import notify_agent_error
from agent.state.tracker import SpendTracker

logger = structlog.get_logger()
console = Console()


async def run_monitor(settings: Settings) -> None:
    """Start the price monitoring loop.  Runs until cancelled (Ctrl-C)."""
    tracker = SpendTracker.load(settings.state_dir)
    provider = get_provider(settings.decision_provider)
    tracer = get_tracer()
    meter = get_meter()

    price_counter = meter.create_counter(
        "price_check_total", description="Total price checks performed"
    )

    async with CoinbaseClient(settings) as client:
        context = AgentContext(
            settings=settings,
            tracker=tracker,
            client=client,
            tracer=tracer,
            meter=meter,
        )

        console.print(
            f"[bold green]Monitoring[/bold green] {settings.coin} "
            f"— target ≤ [bold]${settings.target_price_usd:,.2f}[/bold] "
            f"— polling every {settings.poll_interval_seconds}s "
            f"— decision provider: [bold]{provider.name}[/bold]"
        )
        if settings.dry_run:
            console.print("[yellow]DRY RUN mode — no real orders will be placed[/yellow]")
        if settings.require_approval:
            console.print("[yellow]APPROVAL mode — you will be prompted before each buy[/yellow]")

        while True:
            try:
                await _poll_once(
                    settings=settings,
                    context=context,
                    provider=provider,
                    tracer=tracer,
                    price_counter=price_counter,
                )
            except asyncio.CancelledError:
                logger.info("monitor_stopping")
                break
            except Exception as exc:
                logger.error("monitor_error", error=str(exc), traceback=traceback.format_exc())
                notify_agent_error(settings, coin=settings.coin, error=traceback.format_exc())

            await asyncio.sleep(settings.poll_interval_seconds)


async def _poll_once(
    *,
    settings: Settings,
    context: AgentContext,
    provider,
    tracer: trace.Tracer,
    price_counter: metrics.Counter,
) -> None:
    with tracer.start_as_current_span("price_poll") as span:
        client: CoinbaseClient = context.client  # type: ignore[assignment]
        ticker = await client.get_ticker(settings.coin)
        price = ticker.price_float

        span.set_attribute("coin", settings.coin)
        span.set_attribute("price_usd", price)
        span.set_attribute("target_price_usd", settings.target_price_usd)

        price_counter.add(1, {"coin": settings.coin})

        logger.info(
            "price_checked",
            coin=settings.coin,
            price_usd=price,
            target_usd=settings.target_price_usd,
        )

        if price > settings.target_price_usd:
            return  # price above target — nothing to do

        console.print(
            f"[bold cyan]Price trigger![/bold cyan] "
            f"{settings.coin} = ${price:,.2f} ≤ target ${settings.target_price_usd:,.2f}"
        )
        span.set_attribute("trigger", True)
        context.trigger_price = price

        with tracer.start_as_current_span("jev_decision") as jev_span:
            decision = await _decide(settings, context, provider, price)
            jev_span.set_attribute("action", decision.action)
            jev_span.set_attribute("amount_usd", decision.amount_usd)
            jev_span.set_attribute("conviction", decision.conviction)
            if decision.confidence is not None:
                jev_span.set_attribute("confidence", decision.confidence)
            if decision.errors:
                jev_span.set_attribute("errors", "; ".join(decision.errors))

        logger.info(
            "jev_decision",
            action=decision.action,
            amount_usd=decision.amount_usd,
            conviction=decision.conviction,
            confidence=decision.confidence,
            reasons=decision.reasons,
            errors=decision.errors,
            provider=provider.name,
        )
        console.print(
            f"[magenta]Jev:[/magenta] action={decision.action} "
            f"amount=${decision.amount_usd:.2f} conviction={decision.conviction:.1f} "
            f"confidence={decision.confidence} — {'; '.join(decision.reasons)}"
        )

        if decision.action == "wait":
            return

        if decision.action == "review":
            notify_agent_error(
                settings,
                coin=settings.coin,
                error=(
                    f"Jev flagged for review (no order placed): "
                    f"{'; '.join(decision.reasons)}"
                ),
            )
            return

        # action == "buy" — hand the fixed, pre-computed order to the
        # execution agent (OpenAI Agents SDK: tools + guardrails only).
        execution_agent = build_execution_agent(settings, decision.amount_usd)
        prompt = (
            f"Execute the pre-computed buy: ${decision.amount_usd:.2f} of "
            f"{settings.coin} at trigger price ${price:,.2f}."
        )

        with tracer.start_as_current_span("agent_run") as agent_span:
            try:
                result = await Runner.run(
                    execution_agent,
                    prompt,
                    context=context,
                )
                output = result.final_output
                agent_span.set_attribute("agent_output", str(output)[:500])
                logger.info("agent_completed", output=output)
                console.print(f"[green]Agent:[/green] {output}")
            except InputGuardrailTripwireTriggered as exc:
                reason = str(exc)
                agent_span.set_status(StatusCode.ERROR, reason)
                logger.warning("agent_guardrail_tripped", reason=reason)
                console.print(f"[yellow]Guardrail:[/yellow] {reason}")
            except CoinbaseError as exc:
                agent_span.set_status(StatusCode.ERROR, str(exc))
                logger.error("coinbase_error_in_agent", error=str(exc))
                console.print(f"[red]Coinbase error:[/red] {exc}")
                notify_agent_error(settings, coin=settings.coin, error=str(exc))


async def _decide(settings: Settings, context: AgentContext, provider, price: float):
    """Build state, gather deterministic caps/balance, and call the provider."""
    client: CoinbaseClient = context.client  # type: ignore[assignment]
    tracker = context.tracker

    caps_ok, caps_reason = tracker.can_buy(
        settings.min_buy_usd,
        min_single=settings.min_buy_usd,
        max_single=settings.max_buy_usd,
        max_daily=settings.max_daily_spend_usd,
        max_total=settings.max_total_spend_usd,
        max_per_hour=settings.max_buys_per_hour,
    )
    caps_exceeded = not caps_ok

    usd_balance = await client.get_account_balance("USD")

    state = build_state(
        coin=settings.coin,
        price=price,
        target_price=settings.target_price_usd,
        trigger_price=price,
        usd_balance=usd_balance,
        min_buy_usd=settings.min_buy_usd,
        max_buy_usd=settings.max_buy_usd,
        caps_exceeded=caps_exceeded,
        caps_reason=caps_reason,
    )
    questions = build_questions()

    try:
        answers = provider.decide(state, questions, settings.jev_model)
    except Exception as exc:
        logger.error("jev_provider_error", error=str(exc))
        answers = {}

    return compose_decision(
        answers,
        min_buy_usd=settings.min_buy_usd,
        max_buy_usd=settings.max_buy_usd,
        usd_balance=usd_balance,
        caps_exceeded=caps_exceeded,
        caps_reason=caps_reason,
        confidence_gate=settings.jev_confidence_gate,
        provider_name=provider.name,
    )
