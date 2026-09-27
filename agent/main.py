"""CLI entry point — `crypto-agent monitor` and `crypto-agent status`."""
from __future__ import annotations

import asyncio
import os

import structlog
import typer
from agents import set_default_openai_key
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="crypto-agent",
    help="Autonomous crypto price monitoring and buying agent.",
    add_completion=False,
)
console = Console()
logger = structlog.get_logger()

_logging_configured = False


def _setup() -> None:
    """Lazy one-time initialisation: logging, telemetry, OpenAI key."""
    global _logging_configured
    if _logging_configured:
        return

    from agent.core.config import get_settings
    from agent.core.logging import configure_logging
    from agent.core.telemetry import configure_telemetry

    s = get_settings()
    configure_logging(level=s.log_level, json=s.json_logs)
    configure_telemetry(
        service_name=s.otel_service_name,
        otlp_endpoint=s.otel_exporter_otlp_endpoint,
    )
    os.environ.setdefault("OPENAI_API_KEY", s.openai_api_key)
    set_default_openai_key(s.openai_api_key)
    _logging_configured = True


@app.command()
def monitor(
    coin: str = typer.Option("", help="Override COIN env var, e.g. ETH-USD"),
    target: float = typer.Option(0.0, help="Override TARGET_PRICE_USD"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Log actions without placing orders"),
    require_approval: bool = typer.Option(
        False, "--require-approval", help="Prompt before each buy"
    ),
) -> None:
    """Start the price monitoring loop.

    Polls Coinbase on the configured interval and invokes the buying agent
    whenever the price is at or below the target.
    """
    _setup()

    from agent.core.config import get_settings
    from agent.monitor import run_monitor

    settings = get_settings()

    # CLI flags override env vars
    if coin:
        settings.coin = coin
    if target > 0:
        settings.target_price_usd = target
    if dry_run:
        settings.dry_run = True
    if require_approval:
        settings.require_approval = True

    try:
        asyncio.run(run_monitor(settings))
    except KeyboardInterrupt:
        console.print("\n[bold]Stopped.[/bold]")


@app.command()
def status() -> None:
    """Show the current spend tracker state and guardrail limits."""
    _setup()

    from agent.core.config import get_settings
    from agent.state.tracker import SpendTracker

    settings = get_settings()
    tracker = SpendTracker.load(settings.state_dir)

    table = Table(title="Crypto Buying Agent — Current Status", show_header=True)
    table.add_column("Setting / Metric", style="bold")
    table.add_column("Value")

    table.add_section()
    table.add_row("Coin", settings.coin)
    table.add_row("Target price", f"${settings.target_price_usd:,.2f} USD")
    table.add_row("Poll interval", f"{settings.poll_interval_seconds}s")
    table.add_row("Execution model (OpenAI)", settings.openai_model)
    table.add_row("Decision provider (Jev)", settings.decision_provider)
    table.add_row("Jev model", settings.jev_model)
    table.add_row("Jev confidence gate", f"{settings.jev_confidence_gate:.2f}")
    table.add_row("Sandbox", str(settings.use_sandbox))
    table.add_row("Dry run", str(settings.dry_run))
    table.add_row("Require approval", str(settings.require_approval))

    table.add_section()
    table.add_row("Min buy", f"${settings.min_buy_usd:.2f}")
    table.add_row("Max buy", f"${settings.max_buy_usd:.2f}")
    table.add_row("Max daily spend", f"${settings.max_daily_spend_usd:.2f}")
    table.add_row("Max total spend", f"${settings.max_total_spend_usd:.2f}")
    table.add_row("Max buys / hour", str(settings.max_buys_per_hour))
    table.add_row("Max price drift", f"{settings.max_price_drift_pct:.1f}%")

    table.add_section()
    table.add_row("Total spent (lifetime)", f"${tracker.total_spent:.2f}")
    table.add_row("Spent today (24 h)", f"${tracker.daily_spent():.2f}")
    table.add_row("Buys this hour", str(tracker.hourly_buy_count()))

    console.print(table)


if __name__ == "__main__":
    app()
