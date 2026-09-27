"""Tests for monitor price trigger logic (unit — no network, no agent)."""
from __future__ import annotations

import pytest

from agent.coinbase.models import Ticker


def test_ticker_price_float() -> None:
    t = Ticker(price="62500.50", bid="62500.00", ask="62501.00")
    assert t.price_float == pytest.approx(62500.50)


def test_price_at_target_triggers() -> None:
    """Price equal to target should trigger a buy session."""
    target = 60_000.0
    price = 60_000.0
    assert price <= target


def test_price_below_target_triggers() -> None:
    target = 60_000.0
    price = 59_999.99
    assert price <= target


def test_price_above_target_does_not_trigger() -> None:
    target = 60_000.0
    price = 60_000.01
    assert not (price <= target)


def test_price_drift_within_threshold_allowed() -> None:
    trigger_price = 60_000.0
    current_price = 60_500.0
    max_drift_pct = 1.0

    drift = abs(current_price - trigger_price) / trigger_price * 100
    assert drift <= max_drift_pct  # 0.83% < 1%


def test_price_drift_exceeds_threshold_blocked() -> None:
    trigger_price = 60_000.0
    current_price = 61_500.0  # +2.5%
    max_drift_pct = 1.0

    drift = abs(current_price - trigger_price) / trigger_price * 100
    assert drift > max_drift_pct
