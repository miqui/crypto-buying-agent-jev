"""Application configuration via environment variables / .env file."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_settings: Settings | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── OpenAI (execution layer only — no buy-decision reasoning) ───────────────
    openai_api_key: str
    openai_model: str = "gpt-4.1-mini"

    # ── Jev decision layer (TypeSafe System One via OpenRouter Decisions API) ──
    decision_provider: str = "dry-run"  # "dry-run" | "openrouter"
    jev_model: str = "typesafe/jev-1.13"
    jev_confidence_gate: float = Field(default=0.7, gt=0, le=1)
    openrouter_api_key: str = ""

    # ── Coinbase Exchange API ─────────────────────────────────────────────────
    coinbase_api_key: str
    coinbase_api_secret: str  # base64-encoded HMAC secret
    coinbase_api_passphrase: str
    use_sandbox: bool = False

    # ── Monitoring ────────────────────────────────────────────────────────────
    coin: str = "BTC-USD"
    target_price_usd: float = Field(..., gt=0)
    poll_interval_seconds: int = Field(default=60, ge=5)

    # ── Guardrails ────────────────────────────────────────────────────────────
    min_buy_usd: float = Field(default=10.0, gt=0)
    max_buy_usd: float = Field(default=500.0, gt=0)
    max_daily_spend_usd: float = Field(default=1000.0, gt=0)
    max_total_spend_usd: float = Field(default=5000.0, gt=0)
    max_buys_per_hour: int = Field(default=3, ge=1)
    max_price_drift_pct: float = Field(default=1.0, gt=0)  # % allowed price movement

    # ── Behaviour ─────────────────────────────────────────────────────────────
    require_approval: bool = False  # prompt for confirmation before each buy
    dry_run: bool = False  # log actions without placing real orders

    # ── Email notifications ───────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notify_email: str = ""

    # ── OpenTelemetry ─────────────────────────────────────────────────────────
    otel_exporter_otlp_endpoint: str = ""  # empty → console exporter
    otel_service_name: str = "crypto-buying-agent"

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    json_logs: bool = True

    # ── State persistence ─────────────────────────────────────────────────────
    state_dir: str = ""  # empty → ~/.crypto-buying-agent/


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
