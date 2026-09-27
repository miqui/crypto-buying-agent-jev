"""Decision providers for the Jev buy decision.

DryRunProvider is a deterministic, offline, keyless provider derived directly
from the input state (used for --dry-run, tests, and CI). OpenRouterProvider
calls OpenRouter's Decisions API to run TypeSafe's Jev model. Pattern adapted
from jev-airline-ops-cancel-flights/src/jev_ops/providers.py (verified contract).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Protocol

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"


class DecisionProvider(Protocol):
    name: str

    def decide(self, state: dict, questions: dict, model: str) -> dict:
        """Return a dict of answers keyed by question name."""
        ...


class ProviderError(RuntimeError):
    pass


class DryRunProvider:
    """Deterministic, offline decision provider derived directly from state.

    No network calls, no API key required. Used for --dry-run and tests.
    """

    name = "dry-run"

    def decide(self, state: dict, questions: dict, model: str) -> dict:
        guardrails = state.get("guardrails", {})
        market = state.get("market", {})
        account = state.get("account", {})

        caps_exceeded = bool(guardrails.get("caps_exceeded", False))
        drift = float(market.get("drift_from_trigger_pct", 0.0))
        usd_balance = float(account.get("usd_balance", 0.0))
        min_buy = float(account.get("min_buy_usd", 0.0))

        caps_noul = 0.9 if caps_exceeded else 0.05
        stable_noul = 0.9 if drift <= 1.5 else 0.1
        funds_noul = 0.9 if usd_balance >= min_buy else 0.05

        if caps_exceeded or usd_balance < min_buy:
            action = "review"
        elif drift > 3.0:
            action = "wait"
        else:
            action = "buy"

        if action == "buy":
            conviction_level = 5 if drift <= 0.5 else 4 if drift <= 1.5 else 3
        elif action == "wait":
            conviction_level = 2
        else:
            conviction_level = 1

        def choice_probs(pick: str) -> dict:
            base = {"buy": 0.1, "wait": 0.1, "review": 0.1}
            base[pick] = 0.8
            return base

        # Mirror the real Decisions API `score` contract: a 0-1 normalized
        # score plus a `legend` mapping bucket index "0".."4" to rubric
        # level 1-5 (see typesafe/jev-1.13 live response).
        legend = {
            str(i): {"level": i + 1, "what": f"Conviction level {i + 1}", "signals": []}
            for i in range(5)
        }
        score = (conviction_level - 1) / 4.0

        return {
            "caps_exceeded": {"noul": caps_noul},
            "price_stable": {"noul": stable_noul},
            "funds_available": {"noul": funds_noul},
            "action": {
                "choice": action,
                "probabilities": choice_probs(action),
                "confidence": 0.9,
            },
            "conviction": {
                "score": score,
                "legend": legend,
                "probabilities": {
                    str(i): (1.0 if i == conviction_level else 0.0) for i in range(1, 6)
                },
                "confidence": 0.9,
            },
        }


class OpenRouterProvider:
    """Calls OpenRouter's Decisions API to run Jev (typesafe/jev-1.13)."""

    name = "openrouter"

    def __init__(self, api_key: str | None = None, max_retries: int = 2, timeout: float = 30.0):
        self.api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ProviderError(
                "OPENROUTER_API_KEY is not set. Export it in your environment "
                "or use DECISION_PROVIDER=dry-run to run without the network."
            )
        self.max_retries = max_retries
        self.timeout = timeout

    def decide(self, state: dict, questions: dict, model: str) -> dict:
        body = json.dumps({"model": model, "state": state, "questions": questions}).encode(
            "utf-8"
        )
        req = urllib.request.Request(
            DECISIONS_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                    decision = payload.get("decision", payload)
                    return decision.get("answers", {})
            except urllib.error.HTTPError as e:
                resp_body = e.read().decode("utf-8", errors="replace")
                if e.code in (429,) or e.code >= 500:
                    if attempt < self.max_retries:
                        time.sleep(2**attempt)
                        attempt += 1
                        continue
                    raise ProviderError(
                        f"OpenRouter request failed after retries: HTTP {e.code}: {resp_body}"
                    ) from e
                raise ProviderError(f"OpenRouter request failed: HTTP {e.code}: {resp_body}") from e
            except urllib.error.URLError as e:
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
                    attempt += 1
                    continue
                raise ProviderError(f"OpenRouter request failed: {e}") from e


def get_provider(name: str) -> DecisionProvider:
    if name == "dry-run":
        return DryRunProvider()
    if name == "openrouter":
        return OpenRouterProvider()
    raise ProviderError(f"Unknown DECISION_PROVIDER: {name!r} (expected dry-run|openrouter)")
