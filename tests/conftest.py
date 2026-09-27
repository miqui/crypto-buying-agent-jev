"""Shared fixtures for all test modules."""
from __future__ import annotations

import pytest

import agent.core.config as cfg_mod


@pytest.fixture(autouse=True)
def reset_settings() -> None:
    """Reset the settings singleton between tests."""
    cfg_mod._settings = None
    yield
    cfg_mod._settings = None


@pytest.fixture
def base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject the minimum required environment variables."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("COINBASE_API_KEY", "test-key")
    monkeypatch.setenv("COINBASE_API_SECRET", "dGVzdC1zZWNyZXQ=")  # base64("test-secret")
    monkeypatch.setenv("COINBASE_API_PASSPHRASE", "test-pass")
    monkeypatch.setenv("TARGET_PRICE_USD", "60000")
    monkeypatch.setenv("MIN_BUY_USD", "10")
    monkeypatch.setenv("MAX_BUY_USD", "500")
    monkeypatch.setenv("MAX_DAILY_SPEND_USD", "1000")
    monkeypatch.setenv("MAX_TOTAL_SPEND_USD", "5000")
    monkeypatch.setenv("MAX_BUYS_PER_HOUR", "3")
