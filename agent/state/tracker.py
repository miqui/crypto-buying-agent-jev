"""Spend tracker — enforces all buy guardrails and persists state to disk."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

logger = structlog.get_logger()

_STATE_FILE = "spend_tracker.json"
_DEFAULT_DIR = Path.home() / ".crypto-buying-agent"


def _resolve_state_dir(state_dir: str) -> Path:
    return Path(state_dir) if state_dir else _DEFAULT_DIR


@dataclass
class SpendTracker:
    """Tracks buy activity for guardrail enforcement.

    State is persisted to ``~/.crypto-buying-agent/spend_tracker.json`` (or
    ``STATE_DIR`` if configured) so limits survive process restarts.
    """

    total_spent: float = 0.0
    # (iso-timestamp, amount_usd) pairs — pruned to last 25 h
    spends: list[tuple[str, float]] = field(default_factory=list)
    # iso-timestamps of completed buys — pruned to last 25 h
    buy_timestamps: list[str] = field(default_factory=list)
    _state_dir: Path = field(default_factory=lambda: _DEFAULT_DIR, repr=False, compare=False)

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, state_dir: str = "") -> SpendTracker:
        """Load persisted state; return a fresh tracker if none exists."""
        directory = _resolve_state_dir(state_dir)
        tracker = cls(_state_dir=directory)
        state_file = directory / _STATE_FILE
        if not state_file.exists():
            return tracker
        try:
            data = json.loads(state_file.read_text())
            tracker.total_spent = float(data.get("total_spent", 0.0))
            tracker.spends = [
                (str(ts), float(amt)) for ts, amt in data.get("spends", [])
            ]
            tracker.buy_timestamps = [str(ts) for ts in data.get("buy_timestamps", [])]
            logger.info(
                "tracker_loaded",
                total_spent=tracker.total_spent,
                spends_count=len(tracker.spends),
            )
        except Exception as exc:
            logger.warning("tracker_load_failed", error=str(exc))
        return tracker

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        (self._state_dir / _STATE_FILE).write_text(
            json.dumps(
                {
                    "total_spent": self.total_spent,
                    "spends": self.spends,
                    "buy_timestamps": self.buy_timestamps,
                },
                indent=2,
            )
        )

    # ── Read-only queries ─────────────────────────────────────────────────────

    def daily_spent(self) -> float:
        """Sum of buy amounts in the rolling 24-hour window."""
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        return sum(amt for ts, amt in self.spends if ts >= cutoff)

    def hourly_buy_count(self) -> int:
        """Number of buys in the rolling 1-hour window."""
        cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        return sum(1 for ts in self.buy_timestamps if ts >= cutoff)

    def can_buy(
        self,
        amount_usd: float,
        *,
        min_single: float,
        max_single: float,
        max_daily: float,
        max_total: float,
        max_per_hour: int,
    ) -> tuple[bool, str]:
        """Return ``(True, 'ok')`` or ``(False, reason)``."""
        if amount_usd < min_single:
            return False, f"${amount_usd:.2f} is below minimum ${min_single:.2f}"
        if amount_usd > max_single:
            return False, f"${amount_usd:.2f} exceeds maximum ${max_single:.2f}"

        if self.total_spent + amount_usd > max_total:
            remaining = max_total - self.total_spent
            return (
                False,
                f"Would exceed lifetime cap ${max_total:.2f} "
                f"(remaining: ${remaining:.2f})",
            )

        daily = self.daily_spent()
        if daily + amount_usd > max_daily:
            remaining = max_daily - daily
            return (
                False,
                f"Would exceed daily cap ${max_daily:.2f} "
                f"(spent today: ${daily:.2f}, remaining: ${remaining:.2f})",
            )

        hourly = self.hourly_buy_count()
        if hourly >= max_per_hour:
            return (
                False,
                f"Hourly buy limit of {max_per_hour} reached "
                f"({hourly} buys in the last hour)",
            )

        return True, "ok"

    # ── Mutations ─────────────────────────────────────────────────────────────

    def record_buy(self, amount_usd: float) -> None:
        now = datetime.now(UTC).isoformat()
        self.total_spent += amount_usd
        self.spends.append((now, amount_usd))
        self.buy_timestamps.append(now)
        self._prune()
        self.save()
        logger.info(
            "spend_recorded",
            amount_usd=amount_usd,
            total_spent=self.total_spent,
            daily_spent=self.daily_spent(),
        )

    def _prune(self) -> None:
        """Drop entries older than 25 h to keep lists bounded."""
        cutoff = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        self.spends = [(ts, amt) for ts, amt in self.spends if ts >= cutoff]
        self.buy_timestamps = [ts for ts in self.buy_timestamps if ts >= cutoff]
