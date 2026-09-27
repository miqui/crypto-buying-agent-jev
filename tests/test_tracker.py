"""Tests for the SpendTracker guardrail logic."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent.state.tracker import SpendTracker


def _tracker(tmp_path: Path) -> SpendTracker:
    return SpendTracker(_state_dir=tmp_path)


# ── can_buy ───────────────────────────────────────────────────────────────────


def test_can_buy_passes_clean_state(tmp_path: Path) -> None:
    t = _tracker(tmp_path)
    ok, reason = t.can_buy(
        100.0,
        min_single=10.0,
        max_single=500.0,
        max_daily=1000.0,
        max_total=5000.0,
        max_per_hour=3,
    )
    assert ok
    assert reason == "ok"


def test_can_buy_blocks_below_minimum(tmp_path: Path) -> None:
    t = _tracker(tmp_path)
    ok, reason = t.can_buy(
        5.0, min_single=10.0, max_single=500.0, max_daily=1000.0, max_total=5000.0, max_per_hour=3
    )
    assert not ok
    assert "below minimum" in reason


def test_can_buy_blocks_above_maximum(tmp_path: Path) -> None:
    t = _tracker(tmp_path)
    ok, reason = t.can_buy(
        600.0,
        min_single=10.0,
        max_single=500.0,
        max_daily=1000.0,
        max_total=5000.0,
        max_per_hour=3,
    )
    assert not ok
    assert "exceeds maximum" in reason


def test_can_buy_blocks_lifetime_cap(tmp_path: Path) -> None:
    t = _tracker(tmp_path)
    t.total_spent = 4950.0
    ok, reason = t.can_buy(
        100.0,
        min_single=10.0,
        max_single=500.0,
        max_daily=1000.0,
        max_total=5000.0,
        max_per_hour=3,
    )
    assert not ok
    assert "lifetime cap" in reason


def test_can_buy_blocks_daily_cap(tmp_path: Path) -> None:
    t = _tracker(tmp_path)
    # Simulate 950 USD spent in the last 24h
    now = datetime.now(UTC)
    for _ in range(19):
        ts = (now - timedelta(minutes=10)).isoformat()
        t.spends.append((ts, 50.0))
    ok, reason = t.can_buy(
        100.0,
        min_single=10.0,
        max_single=500.0,
        max_daily=1000.0,
        max_total=5000.0,
        max_per_hour=3,
    )
    assert not ok
    assert "daily cap" in reason


def test_can_buy_blocks_hourly_rate(tmp_path: Path) -> None:
    t = _tracker(tmp_path)
    now = datetime.now(UTC)
    for _ in range(3):
        t.buy_timestamps.append((now - timedelta(minutes=5)).isoformat())
    ok, reason = t.can_buy(
        50.0,
        min_single=10.0,
        max_single=500.0,
        max_daily=1000.0,
        max_total=5000.0,
        max_per_hour=3,
    )
    assert not ok
    assert "Hourly buy limit" in reason


# ── record_buy + persistence ──────────────────────────────────────────────────


def test_record_buy_updates_totals(tmp_path: Path) -> None:
    t = _tracker(tmp_path)
    t.record_buy(250.0)
    assert t.total_spent == 250.0
    assert t.daily_spent() == 250.0
    assert t.hourly_buy_count() == 1


def test_record_buy_persists_to_disk(tmp_path: Path) -> None:
    t = _tracker(tmp_path)
    t.record_buy(123.45)

    reloaded = SpendTracker.load(str(tmp_path))
    assert reloaded.total_spent == pytest.approx(123.45, rel=1e-6)
    assert reloaded.hourly_buy_count() == 1


def test_old_entries_excluded_from_daily(tmp_path: Path) -> None:
    t = _tracker(tmp_path)
    old_ts = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    t.spends.append((old_ts, 999.0))
    assert t.daily_spent() == 0.0


def test_old_entries_excluded_from_hourly(tmp_path: Path) -> None:
    t = _tracker(tmp_path)
    old_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    t.buy_timestamps.append(old_ts)
    assert t.hourly_buy_count() == 0
