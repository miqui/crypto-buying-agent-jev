"""Builds the Jev `state` payload and fixed `questions` dict for a buy decision.

Deterministic caps/balance checks stay in code (SpendTracker.can_buy, live
balance fetch); Jev only judges price stability and overall conviction.
"""
from __future__ import annotations


def build_state(
    *,
    coin: str,
    price: float,
    target_price: float,
    trigger_price: float,
    usd_balance: float,
    min_buy_usd: float,
    max_buy_usd: float,
    caps_exceeded: bool,
    caps_reason: str,
) -> dict:
    """Subset of live market/account/guardrail data, nested for the questions."""
    drift_pct = (
        abs(price - trigger_price) / trigger_price * 100 if trigger_price else 0.0
    )
    return {
        "market": {
            "coin": coin,
            "current_price_usd": round(price, 2),
            "target_price_usd": round(target_price, 2),
            "trigger_price_usd": round(trigger_price, 2),
            "drift_from_trigger_pct": round(drift_pct, 4),
        },
        "account": {
            "usd_balance": round(usd_balance, 2),
            "min_buy_usd": min_buy_usd,
            "max_buy_usd": max_buy_usd,
        },
        "guardrails": {
            "caps_exceeded": caps_exceeded,
            "caps_reason": caps_reason,
        },
    }


def build_questions() -> dict:
    """Fixed question set: 3 noul + 1 choice + 1 score, evaluated in parallel.

    noul answers carry no `confidence` field by API contract — the gate in
    compose.py only reads confidence off the choice and score answers.
    """
    return {
        "caps_exceeded": {
            "type": "noul",
            "instructions": (
                "Given `guardrails.caps_exceeded` and `guardrails.caps_reason`, "
                "have the spend/rate guardrails already been tripped, meaning "
                "no buy should be attempted regardless of price?"
            ),
            "criteria": {
                "true": {
                    "what": (
                        "`guardrails.caps_exceeded` is true — a daily, "
                        "lifetime, or hourly cap has already been reached."
                    ),
                    "not_for": "`guardrails.caps_exceeded` is false.",
                    "examples": [
                        "caps_exceeded=true, caps_reason='daily cap reached'",
                    ],
                },
                "false": {
                    "what": "`guardrails.caps_exceeded` is false — room remains under all caps.",
                    "not_for": "`guardrails.caps_exceeded` is true.",
                    "examples": ["caps_exceeded=false, caps_reason=''"],
                },
            },
        },
        "price_stable": {
            "type": "noul",
            "instructions": (
                "Given `market.drift_from_trigger_pct`, has the price stayed "
                "close enough to the trigger price that acting on it now is "
                "still reasonable (small drift = stable)?"
            ),
            "criteria": {
                "true": {
                    "what": "Drift from the trigger price is small (roughly under 1-2%).",
                    "not_for": "Drift is large, meaning the trigger is stale.",
                    "examples": ["drift_from_trigger_pct=0.3", "drift_from_trigger_pct=0.9"],
                },
                "false": {
                    "what": "Drift from the trigger price is large — the opportunity may have moved on.",
                    "not_for": "Drift is small.",
                    "examples": ["drift_from_trigger_pct=4.5", "drift_from_trigger_pct=10.0"],
                },
            },
        },
        "funds_available": {
            "type": "noul",
            "instructions": (
                "Given `account.usd_balance` compared against `account.min_buy_usd`, "
                "is there enough USD balance to place at least a minimum-sized buy?"
            ),
            "criteria": {
                "true": {
                    "what": "`account.usd_balance` is at or above `account.min_buy_usd`.",
                    "not_for": "Balance is below the minimum buy size.",
                    "examples": ["usd_balance=200, min_buy_usd=10"],
                },
                "false": {
                    "what": "`account.usd_balance` is below `account.min_buy_usd`.",
                    "not_for": "Balance covers at least the minimum buy.",
                    "examples": ["usd_balance=5, min_buy_usd=10"],
                },
            },
        },
        "action": {
            "type": "choice",
            "instructions": (
                "Given the market, account, and guardrail state, what should "
                "happen with this buy opportunity right now?"
            ),
            "criteria": {
                "buy": {
                    "what": (
                        "Guardrails are clear, the price is stable near the "
                        "trigger, and funds are available — proceed with a buy."
                    ),
                    "not_for": "Caps are exceeded, funds are insufficient, or price has drifted heavily.",
                    "examples": ["caps_exceeded=false, price stable, funds available"],
                },
                "wait": {
                    "what": (
                        "No hard blocker, but the price has drifted enough "
                        "that waiting for the next poll is more prudent than "
                        "buying immediately."
                    ),
                    "not_for": "Price is stable and funds/caps are fine (buy), or a hard blocker exists (review).",
                    "examples": ["drift_from_trigger_pct=3.5, caps_exceeded=false"],
                },
                "review": {
                    "what": (
                        "A hard blocker exists — caps exceeded or insufficient "
                        "funds — that a human should be made aware of."
                    ),
                    "not_for": "No hard blocker exists.",
                    "examples": ["caps_exceeded=true", "usd_balance below min_buy_usd"],
                },
            },
        },
        "conviction": {
            "type": "score",
            "instructions": (
                "On a 1-5 rubric, how strong is the conviction to buy given "
                "how far below target the price is and how stable it looks?"
            ),
            "criteria": [
                {
                    "level": 1,
                    "what": "Weak conviction — price barely touched target, or is drifting.",
                    "signals": ["price just at target", "noticeable drift"],
                },
                {
                    "level": 2,
                    "what": "Below-average conviction — marginal dip, some uncertainty.",
                    "signals": ["small dip below target", "minor drift"],
                },
                {
                    "level": 3,
                    "what": "Moderate conviction — a clear, stable dip below target.",
                    "signals": ["clear dip", "low drift"],
                },
                {
                    "level": 4,
                    "what": "Strong conviction — a solid dip below target with a stable price.",
                    "signals": ["solid dip", "near-zero drift"],
                },
                {
                    "level": 5,
                    "what": "Very strong conviction — a large, stable dip well below target.",
                    "signals": ["large dip", "very stable price"],
                },
            ],
        },
    }
