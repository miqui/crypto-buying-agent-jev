"""Keyless, network-free tests for the Jev decision layer."""
from __future__ import annotations

from agent.jev.compose import compose_decision
from agent.jev.providers import DryRunProvider, OpenRouterProvider, ProviderError, get_provider
from agent.jev.questions import build_questions, build_state


def test_build_state_shape() -> None:
    state = build_state(
        coin="BTC-USD",
        price=59_000.0,
        target_price=60_000.0,
        trigger_price=59_000.0,
        usd_balance=200.0,
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        caps_exceeded=False,
        caps_reason="ok",
    )
    assert state["market"]["coin"] == "BTC-USD"
    assert state["account"]["usd_balance"] == 200.0
    assert state["guardrails"]["caps_exceeded"] is False


def test_build_questions_has_expected_names() -> None:
    q = build_questions()
    assert set(q.keys()) == {
        "caps_exceeded",
        "price_stable",
        "funds_available",
        "action",
        "conviction",
    }
    assert q["action"]["type"] == "choice"
    assert q["conviction"]["type"] == "score"
    assert q["caps_exceeded"]["type"] == "noul"


def test_dry_run_provider_is_deterministic() -> None:
    provider = DryRunProvider()
    state = build_state(
        coin="BTC-USD",
        price=59_000.0,
        target_price=60_000.0,
        trigger_price=59_000.0,
        usd_balance=200.0,
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        caps_exceeded=False,
        caps_reason="ok",
    )
    questions = build_questions()
    a1 = provider.decide(state, questions, "typesafe/jev-1.13")
    a2 = provider.decide(state, questions, "typesafe/jev-1.13")
    assert a1 == a2
    assert a1["action"]["choice"] == "buy"


def test_dry_run_provider_caps_exceeded_forces_review() -> None:
    provider = DryRunProvider()
    state = build_state(
        coin="BTC-USD",
        price=59_000.0,
        target_price=60_000.0,
        trigger_price=59_000.0,
        usd_balance=200.0,
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        caps_exceeded=True,
        caps_reason="daily cap reached",
    )
    answers = provider.decide(state, build_questions(), "typesafe/jev-1.13")
    assert answers["action"]["choice"] == "review"


def test_openrouter_provider_requires_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    try:
        OpenRouterProvider(api_key=None)
        raised = False
    except ProviderError:
        raised = True
    assert raised


def test_get_provider_dry_run() -> None:
    assert get_provider("dry-run").name == "dry-run"


def test_get_provider_unknown_raises() -> None:
    try:
        get_provider("nonsense")
        raised = False
    except ProviderError:
        raised = True
    assert raised


def test_compose_decision_buy_sizes_amount_by_conviction() -> None:
    answers = {
        "caps_exceeded": {"noul": 0.05},
        "price_stable": {"noul": 0.9},
        "funds_available": {"noul": 0.9},
        "action": {"choice": "buy", "confidence": 0.9},
        "conviction": {"score": 5.0, "confidence": 0.9},
    }
    decision = compose_decision(
        answers,
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        usd_balance=1000.0,
        caps_exceeded=False,
        caps_reason="",
    )
    assert decision.action == "buy"
    assert decision.amount_usd == 500.0  # max conviction -> max amount


def test_compose_decision_caps_exceeded_overrides_to_review() -> None:
    """Code-level caps check always wins, even if Jev said buy."""
    answers = {
        "caps_exceeded": {"noul": 0.05},
        "price_stable": {"noul": 0.9},
        "funds_available": {"noul": 0.9},
        "action": {"choice": "buy", "confidence": 0.9},
        "conviction": {"score": 5.0, "confidence": 0.9},
    }
    decision = compose_decision(
        answers,
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        usd_balance=1000.0,
        caps_exceeded=True,
        caps_reason="daily cap reached",
    )
    assert decision.action == "review"
    assert decision.amount_usd == 0.0


def test_compose_decision_insufficient_balance_overrides_to_review() -> None:
    answers = {
        "caps_exceeded": {"noul": 0.05},
        "price_stable": {"noul": 0.9},
        "funds_available": {"noul": 0.05},
        "action": {"choice": "buy", "confidence": 0.9},
        "conviction": {"score": 3.0, "confidence": 0.9},
    }
    decision = compose_decision(
        answers,
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        usd_balance=5.0,
        caps_exceeded=False,
        caps_reason="",
    )
    assert decision.action == "review"


def test_compose_decision_low_confidence_gates_to_review() -> None:
    answers = {
        "caps_exceeded": {"noul": 0.05},
        "price_stable": {"noul": 0.9},
        "funds_available": {"noul": 0.9},
        "action": {"choice": "buy", "confidence": 0.3},
        "conviction": {"score": 3.0, "confidence": 0.9},
    }
    decision = compose_decision(
        answers,
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        usd_balance=1000.0,
        caps_exceeded=False,
        caps_reason="",
        confidence_gate=0.7,
    )
    assert decision.action == "review"


def test_compose_decision_missing_fields_recorded_as_errors_not_crash() -> None:
    decision = compose_decision(
        {},
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        usd_balance=1000.0,
        caps_exceeded=False,
        caps_reason="",
    )
    assert decision.errors  # missing noul/choice/score all recorded
    assert decision.action in {"buy", "wait", "review"}  # never crashes


def test_compose_decision_wait_action_has_zero_amount() -> None:
    answers = {
        "caps_exceeded": {"noul": 0.05},
        "price_stable": {"noul": 0.1},
        "funds_available": {"noul": 0.9},
        "action": {"choice": "wait", "confidence": 0.9},
        "conviction": {"score": 2.0, "confidence": 0.9},
    }
    decision = compose_decision(
        answers,
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        usd_balance=1000.0,
        caps_exceeded=False,
        caps_reason="",
    )
    assert decision.action == "wait"
    assert decision.amount_usd == 0.0


def test_rubric_conviction_normalized_score_no_legend() -> None:
    """0-1 normalized score with no legend falls back to score*4+1."""
    from agent.jev.compose import _rubric_conviction

    assert _rubric_conviction(0.0) == 1.0
    assert _rubric_conviction(1.0) == 5.0
    assert _rubric_conviction(0.5) == 3.0


def test_rubric_conviction_with_legend_maps_bucket_to_level() -> None:
    """Real API shape: legend maps bucket index '0'..'4' to a rubric level."""
    from agent.jev.compose import _rubric_conviction

    legend = {
        "0": {"level": 1, "what": "Weak"},
        "1": {"level": 2, "what": "Below-average"},
        "2": {"level": 3, "what": "Moderate"},
        "3": {"level": 4, "what": "Strong"},
        "4": {"level": 5, "what": "Very strong"},
    }
    # 0.88 -> bucket round(0.88*4)=round(3.52)=4 -> level 5
    assert _rubric_conviction(0.88, legend) == 5.0
    assert _rubric_conviction(0.0, legend) == 1.0
    assert _rubric_conviction(0.5, legend) == 3.0


def test_rubric_conviction_legacy_value_above_one_passthrough() -> None:
    """Values already >1.0 are treated as legacy 1-5 rubric values."""
    from agent.jev.compose import _rubric_conviction

    assert _rubric_conviction(5.0) == 5.0
    assert _rubric_conviction(3.0, {"0": {"level": 1}}) == 3.0


def test_compose_decision_converts_live_api_normalized_score_shape() -> None:
    """Mirror the live 0.88 score + legend response: conviction=4.52, sized near max."""
    answers = {
        "caps_exceeded": {"noul": 0.05},
        "price_stable": {"noul": 0.9},
        "funds_available": {"noul": 0.9},
        "action": {"choice": "buy", "confidence": 0.9},
        "conviction": {
            "score": 0.88,
            "legend": {
                "0": {"level": 1, "what": "Weak"},
                "1": {"level": 2, "what": "Below-average"},
                "2": {"level": 3, "what": "Moderate"},
                "3": {"level": 4, "what": "Strong"},
                "4": {"level": 5, "what": "Very strong"},
            },
            "confidence": 0.85,
        },
    }
    decision = compose_decision(
        answers,
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        usd_balance=1000.0,
        caps_exceeded=False,
        caps_reason="",
    )
    assert decision.action == "buy"
    assert decision.conviction == 5.0
    assert decision.amount_usd == 500.0
    assert any("conviction=5.0" in r for r in decision.reasons)


def test_compose_decision_normalized_score_no_legend_sizing() -> None:
    """0.88 score without legend -> fallback linear conviction 4.52, sized toward max."""
    answers = {
        "caps_exceeded": {"noul": 0.05},
        "price_stable": {"noul": 0.9},
        "funds_available": {"noul": 0.9},
        "action": {"choice": "buy", "confidence": 0.9},
        "conviction": {"score": 0.88, "confidence": 0.85},
    }
    decision = compose_decision(
        answers,
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        usd_balance=1000.0,
        caps_exceeded=False,
        caps_reason="",
    )
    assert decision.action == "buy"
    assert decision.conviction == 4.52
    # frac = (4.52-1)/4 = 0.88 -> amount = 10 + 0.88*(490) = 441.2
    assert decision.amount_usd == 441.2


def test_dry_run_provider_returns_normalized_score_with_legend() -> None:
    """DryRunProvider mirrors the live API's 0-1 normalized + legend shape."""
    provider = DryRunProvider()
    state = build_state(
        coin="BTC-USD",
        price=59_000.0,
        target_price=60_000.0,
        trigger_price=59_000.0,
        usd_balance=200.0,
        min_buy_usd=10.0,
        max_buy_usd=500.0,
        caps_exceeded=False,
        caps_reason="ok",
    )
    answers = provider.decide(state, build_questions(), "typesafe/jev-1.13")
    conviction_answer = answers["conviction"]
    assert 0.0 <= conviction_answer["score"] <= 1.0
    assert "legend" in conviction_answer
    assert set(conviction_answer["legend"].keys()) == {"0", "1", "2", "3", "4"}
    for bucket in conviction_answer["legend"].values():
        assert 1 <= bucket["level"] <= 5
