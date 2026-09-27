"""Composition of Jev answers into a final buy Decision.

Deterministic logic lives here in code; the model only answers atomic
questions (judgment: price stability, action, conviction). Caps/balance
checks are computed in code *before* calling Jev (see monitor.py) and passed
in as state — Jev never owns them, it only reacts to them.

Confidence contract (per the Jev/OpenRouter API): noul answers never carry a
`confidence` field — that is expected, not an error. Only `choice` and
`score` answers carry confidence. Decision-level confidence is taken from the
`action` choice answer, falling back to the `conviction` score answer if the
choice confidence is missing; blank only if neither is present. Parse
defensively so one bad question fails one decision, not the whole run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MIN_CONVICTION = 1
MAX_CONVICTION = 5
CONFIDENCE_GATE = 0.7


@dataclass
class Decision:
    action: str  # "buy" | "wait" | "review"
    amount_usd: float
    confidence: float | None
    conviction: float
    reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    provider: str = ""


def _get(d: dict, key: str, default=None):
    try:
        return d.get(key, default)
    except AttributeError:
        return default


def _rubric_conviction(score: float, legend: dict | None = None) -> float:
    """Convert a raw Jev `score` answer into the 1-5 conviction rubric.

    The Decisions API `score` primitive returns a 0-1 NORMALIZED value plus an
    optional `legend` dict mapping "0".."4" (bucket index) to a rubric level
    1-5 with a description. If `legend` is present, use it to resolve the
    discrete rubric level for the score's bucket. If absent and the score is
    within 0-1, fall back to the linear mapping score*4+1. Values already
    above 1.0 are treated as legacy/pre-normalized 1-5 rubric values and
    passed through unchanged (robustness for older callers/tests).
    """
    if score > 1.0:
        return score
    if legend:
        idx = min(4, max(0, round(score * 4)))
        bucket = legend.get(str(idx))
        if isinstance(bucket, dict) and "level" in bucket:
            try:
                return float(bucket["level"])
            except (TypeError, ValueError):
                pass
    return score * 4 + 1


def _size_amount(conviction: float, min_buy_usd: float, max_buy_usd: float) -> float:
    """Map conviction 1-5 linearly into [min_buy_usd, max_buy_usd]."""
    span = MAX_CONVICTION - MIN_CONVICTION
    if span <= 0:
        return min_buy_usd
    frac = (conviction - MIN_CONVICTION) / span
    frac = min(1.0, max(0.0, frac))
    return round(min_buy_usd + frac * (max_buy_usd - min_buy_usd), 2)


def compose_decision(
    answers: dict,
    *,
    min_buy_usd: float,
    max_buy_usd: float,
    usd_balance: float,
    caps_exceeded: bool,
    caps_reason: str,
    confidence_gate: float = CONFIDENCE_GATE,
    provider_name: str = "",
) -> Decision:
    errors: list[str] = []
    reasons: list[str] = []

    def noul(name: str) -> float:
        a = _get(answers, name, {}) or {}
        val = _get(a, "noul")
        if val is None:
            errors.append(f"missing noul for {name}")
            return 0.0
        try:
            return float(val)
        except (TypeError, ValueError):
            errors.append(f"non-numeric noul for {name}")
            return 0.0

    caps_exceeded_noul = noul("caps_exceeded")
    price_stable_noul = noul("price_stable")
    funds_available_noul = noul("funds_available")

    action_answer = _get(answers, "action", {}) or {}
    action = _get(action_answer, "choice")
    action_conf = _get(action_answer, "confidence")
    if action is None:
        errors.append("missing choice for action")
        action = "review"
    if action_conf is not None:
        try:
            action_conf = float(action_conf)
        except (TypeError, ValueError):
            errors.append("non-numeric confidence for action")
            action_conf = None

    conviction_answer = _get(answers, "conviction", {}) or {}
    conviction_raw = _get(conviction_answer, "score")
    conviction_legend = _get(conviction_answer, "legend")
    conviction_conf = _get(conviction_answer, "confidence")
    if conviction_raw is None:
        errors.append("missing score for conviction")
        conviction = float(MIN_CONVICTION)
    else:
        try:
            conviction_raw = float(conviction_raw)
            conviction = _rubric_conviction(conviction_raw, conviction_legend)
        except (TypeError, ValueError):
            errors.append("non-numeric score for conviction")
            conviction = float(MIN_CONVICTION)
    if conviction_conf is not None:
        try:
            conviction_conf = float(conviction_conf)
        except (TypeError, ValueError):
            errors.append("non-numeric confidence for conviction")
            conviction_conf = None

    # Decision-level confidence: choice confidence first, then score
    # confidence, blank if neither answer carried one. noul answers never
    # carry confidence — that is expected, not an error.
    confidence = action_conf if action_conf is not None else conviction_conf

    # Deterministic overrides: hard blockers computed in code always win,
    # regardless of what Jev answered, per the "code owns caps/balance" rule.
    if caps_exceeded:
        action = "review"
        reasons.append(f"caps exceeded (code check): {caps_reason}")
    elif usd_balance < min_buy_usd:
        action = "review"
        reasons.append(
            f"insufficient balance (code check): ${usd_balance:.2f} < min ${min_buy_usd:.2f}"
        )

    if caps_exceeded_noul >= 0.5:
        reasons.append("Jev flagged caps_exceeded")
    if price_stable_noul < 0.5:
        reasons.append("Jev flagged price not stable")
    if funds_available_noul < 0.5:
        reasons.append("Jev flagged funds not available")
    reasons.append(f"Jev action={action} conviction={conviction:.1f}")

    review_gate = confidence is not None and confidence < confidence_gate
    if review_gate and action == "buy":
        reasons.append(f"confidence {confidence:.2f} below gate {confidence_gate:.2f}")
        action = "review"

    amount_usd = 0.0
    if action == "buy":
        amount_usd = _size_amount(conviction, min_buy_usd, max_buy_usd)
        amount_usd = min(amount_usd, usd_balance, max_buy_usd)
        amount_usd = max(amount_usd, min_buy_usd) if amount_usd >= min_buy_usd else amount_usd

    return Decision(
        action=action,
        amount_usd=amount_usd,
        confidence=confidence,
        conviction=conviction,
        reasons=reasons,
        errors=errors,
        provider=provider_name,
    )
