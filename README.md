# crypto-buying-agent-jev

<img width="791" height="1221" alt="jev-crypto drawio" src="https://github.com/user-attachments/assets/0bf19c8b-98ef-4568-b23f-1f5db1147c55" />



Autonomous crypto price monitoring agent where the **buy decision** is made by
[TypeSafe Jev (System One)](https://openrouter.ai) via the OpenRouter
Decisions API, and the [OpenAI Agents Python SDK](https://openai.github.io/openai-agents-python/)
is used purely as the **tool/execution layer** against the
[Coinbase Exchange REST API](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/introduction).

Variant of `crypto-buying-agent`: the GPT-4.1-mini free-form buy reasoning is
replaced by a structured, typed decision model. The OpenAI agent no longer
decides *whether* or *how much* to buy — it only confirms price, confirms
balance, and executes the pre-computed order.

## Design

```
monitor loop (poll price → target hit?)
        │
        ▼
build Jev state ──► OpenRouter /api/alpha/decisions (typesafe/jev-1.13)
        │                  atomic questions (one request, parallel):
        │                    noul   caps_exceeded / price_stable / funds_available
        │                    choice action ∈ {buy, wait, review}
        │                    score  conviction 1–5
        ▼
compose.py (pure code, deterministic)
        weighted sum + named constants; confidence gate → review flag
        outputs: Decision(action, amount_usd, confidence, reasons[])
        │
        ├─ action=buy & confidence ≥ gate ─► OpenAI Agents SDK run
        │        agent = execution engine only (fixed instructions:
        │        "confirm price, confirm balance, execute $X order")
        │        tools: get_current_price / get_account_balance / place_buy_order
        │        (all 7 guardrails still enforced inside place_buy_order)
        ├─ action=review / low confidence ─► notify + log, NO order
        └─ action=wait ─► log, continue polling
```

### The Jev question set

Jev is a *decision* model, not a chat model: it receives a typed `state` and a
set of typed questions, and returns typed answers — no text generation. All 5
questions below are sent in **one request** to the OpenRouter Decisions API
(`typesafe/jev-1.13`) and evaluated in parallel and in isolation (no
context-rot between them).

Three primitive types are used (`agent/jev/questions.py`):

- **noul** (×3) — a yes/no judgment answering "is this true for this state?"
  Criteria are a record with `true` / `false` entries, each carrying `what`,
  `not_for`, and `examples`.
  - `caps_exceeded` — have the spend/rate guardrails already been tripped?
  - `price_stable` — is drift from the trigger price still small enough to act?
  - `funds_available` — does the USD balance cover at least a minimum buy?

- **choice** (×1) — pick one option from a fixed set. Criteria are a record
  mapping each option name to its description.
  - `action` ∈ `buy` / `wait` / `review` — what should happen with this buy
    opportunity right now?

- **score** (×1) — rate against a rubric. Criteria are an array of level
  objects (`what` + `signals`).
  - `conviction` — 1–5 rubric: how strong is the conviction to buy, given how
    far below target the price is and how stable it looks?

Answer fields per primitive:

| Primitive | Answer fields | `confidence`? |
| --- | --- | --- |
| noul | `noul` (0–1) | never — by API contract |
| choice | `choice`, `probabilities` | yes |
| score | `score`, `legend` | yes |

Notes the composer relies on:

- `noul` answers carry no `confidence` — that is expected, not an error. The
  confidence gate reads confidence only from the `action` (choice) and
  `conviction` (score) answers, choice first.
- The live API returns the score primitive as a **0–1 normalized value** with
  a `legend` mapping that range onto the 1–5 rubric levels (e.g. `0.86` →
  level 4). `compose_decision` converts it before anything else; the
  dry-run provider returns the same normalized+legend shape so tests mirror
  the real contract.
- Composition: the `noul` signals plus deterministic cap/balance checks
  (computed in code and passed in as `state`) can hard-block to `review`;
  otherwise `action` decides and `conviction` sizes the order (converted
  1–5 value mapped linearly into `[MIN_BUY_USD, MAX_BUY_USD]`, then clamped
  by caps/balance in code).

Design rules:
- **Deterministic checks stay in code.** Spend caps, hourly rate, and USD
  balance are computed by `SpendTracker`/`CoinbaseClient` *before* Jev is
  called, passed into its `state`, and re-applied as hard overrides in
  `compose.py` — Jev's judgment can never contradict them.
- **Jev only supplies judgment**: is the price still stable vs. the trigger,
  what action fits (buy/wait/review), and how strong is the conviction — that
  conviction score is what sizes the order (linearly mapped into
  `[MIN_BUY_USD, MAX_BUY_USD]`, then clamped by caps/balance in code).
- **Confidence gate**: `noul` answers never carry `confidence` — only the
  `action` (choice) and `conviction` (score) answers do. If the best
  available confidence is below `JEV_CONFIDENCE_GATE` (default 0.7), or a
  code-level cap/balance check fails, the decision is forced to `review` and
  no order is placed.
- **Two providers**: `DryRunProvider` (deterministic, offline, keyless — used
  by default, tests, and CI) and `OpenRouterProvider` (real Jev call).
  Selected by `DECISION_PROVIDER=dry-run|openrouter`.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) 0.4+
- Coinbase Exchange API credentials (key, secret, passphrase)
- OpenAI API key (execution layer)
- OpenRouter API key (only if `DECISION_PROVIDER=openrouter`)

## Installation

```bash
uv sync
```

## Configuration

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | ✅ | — | OpenAI API key (execution layer only) |
| `OPENAI_MODEL` | | `gpt-4.1-mini` | Execution agent model |
| `DECISION_PROVIDER` | | `dry-run` | `dry-run` (offline, keyless) or `openrouter` (real Jev) |
| `JEV_MODEL` | | `typesafe/jev-1.13` | Jev model id passed to the Decisions API |
| `JEV_CONFIDENCE_GATE` | | `0.7` | Below this confidence, force `review` (never guess) |
| `OPENROUTER_API_KEY` | only if `openrouter` | — | OpenRouter API key |
| `COINBASE_API_KEY` | ✅ | — | Coinbase Exchange API key |
| `COINBASE_API_SECRET` | ✅ | — | Base64-encoded HMAC secret |
| `COINBASE_API_PASSPHRASE` | ✅ | — | API passphrase |
| `USE_SANDBOX` | | `false` | Use Coinbase sandbox |
| `COIN` | | `BTC-USD` | Trading pair to monitor |
| `TARGET_PRICE_USD` | ✅ | — | Buy trigger price (≤ triggers a Jev decision) |
| `POLL_INTERVAL_SECONDS` | | `60` | How often to check the price |
| `MIN_BUY_USD` | | `10.0` | Minimum single order size |
| `MAX_BUY_USD` | | `500.0` | Maximum single order size |
| `MAX_DAILY_SPEND_USD` | | `1000.0` | Rolling 24 h spend cap |
| `MAX_TOTAL_SPEND_USD` | | `5000.0` | Lifetime spend cap |
| `MAX_BUYS_PER_HOUR` | | `3` | Max orders per rolling hour |
| `MAX_PRICE_DRIFT_PCT` | | `1.0` | Abort if price moved > X% since trigger |
| `REQUIRE_APPROVAL` | | `false` | Prompt before each buy |
| `DRY_RUN` | | `false` | Log actions without placing real Coinbase orders |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `NOTIFY_EMAIL` | | — | Email on buy / guardrail / review |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | | — | OTLP endpoint (blank → stdout) |
| `OTEL_SERVICE_NAME` | | `crypto-buying-agent` | Service name in traces |
| `LOG_LEVEL` / `JSON_LOGS` | | `INFO` / `true` | Logging config |
| `STATE_DIR` | | `~/.crypto-buying-agent/` | Spend tracker persistence dir |

## Running tests

```bash
uv run pytest -v
```

Keyless, network-free: 41 tests pass — Coinbase auth/client mocks, spend
tracker, price-trigger logic, and the full Jev decision layer (state
building, question shape, `DryRunProvider` determinism, `compose_decision`
overrides for caps/balance/confidence).

## Run manually

Commands actually executed against this repo, with the output seen:

```bash
$ uv sync
Resolved ... packages ... (clean install into .venv)

$ uv run ruff check agent tests
All checks passed!

$ uv run pytest -q
...............................................                          [100%]
47 passed in 0.08s

$ uv run crypto-agent status   # with dummy Coinbase/OpenAI creds, USE_SANDBOX=true
Crypto Buying Agent — Current Status
┏━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Setting / Metric         ┃ Value                 ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━┩
│ Coin                     │ BTC-USD               │
│ Decision provider (Jev)  │ dry-run               │
│ Jev model                │ typesafe/jev-1.13     │
│ Jev confidence gate      │ 0.70                  │
...

# Direct Jev decision-path smoke test (no Coinbase network needed):
$ uv run python -c "
from agent.core.config import Settings
from agent.jev.compose import compose_decision
from agent.jev.providers import get_provider
from agent.jev.questions import build_state, build_questions
s = Settings()
provider = get_provider(s.decision_provider)
state = build_state(coin=s.coin, price=59000.0, target_price=s.target_price_usd,
                     trigger_price=59000.0, usd_balance=200.0,
                     min_buy_usd=s.min_buy_usd, max_buy_usd=s.max_buy_usd,
                     caps_exceeded=False, caps_reason='ok')
answers = provider.decide(state, build_questions(), s.jev_model)
decision = compose_decision(answers, min_buy_usd=s.min_buy_usd, max_buy_usd=s.max_buy_usd,
                             usd_balance=200.0, caps_exceeded=False, caps_reason='',
                             confidence_gate=s.jev_confidence_gate, provider_name=provider.name)
print('DECISION ROW:', decision)
"
DECISION ROW: Decision(action='buy', amount_usd=200.0, confidence=0.9, conviction=5.0,
  reasons=['Jev action=buy conviction=5.0'], errors=[], provider='dry-run')
```

`uv run crypto-agent monitor` requires real Coinbase Exchange sandbox/production
credentials (it polls the live/sandbox ticker) — not exercised here since only
dummy credentials were available; the CLI wiring and the full Jev decision
path were verified directly instead (above).

Live Jev smoke test (real `OPENROUTER_API_KEY` in the environment,
`DECISION_PROVIDER=openrouter`, one request to
`https://openrouter.ai/api/alpha/decisions` with `typesafe/jev-1.13`):

```
live: action=buy conf=0.55 raw_score=0.86
DECISION: Decision(action='review', amount_usd=0.0, confidence=0.55,
  conviction=4.0, reasons=['Jev action=buy conviction=4.0',
  'confidence 0.55 below gate 0.70'], errors=[], provider='')
```

The real API returns the `score` primitive as a 0-1 normalized value with a
`legend` mapping 0-1 onto the 1-5 rubric levels; `compose_decision` converts
it before sizing. Note: Jev's `action` confidence hovered around 0.55-0.58
across both live runs for this synthetic state, below the default 0.70 gate —
if your live states trip `review` too often, tune `JEV_CONFIDENCE_GATE`.

## Project structure

```
agent/
  main.py              CLI entry point (typer)
  agent.py             Execution agent (fixed instructions, no decision logic)
  monitor.py           Price polling loop → Jev decision → execution agent
  context.py           AgentContext dataclass
  jev/
    questions.py        build_state() / build_questions() — Jev question set
    providers.py         DryRunProvider (deterministic) + OpenRouterProvider
    compose.py           compose_decision() — deterministic composition + gates
  core/
    config.py          pydantic-settings (all env vars, incl. Jev config)
    logging.py          structlog JSON to stdout
    telemetry.py         OpenTelemetry traces + metrics
  coinbase/
    auth.py             HMAC-SHA256 request signing
    client.py            Async Coinbase Exchange client
    models.py             Pydantic API response models
  tools/
    price.py             get_current_price tool
    account.py            get_account_balance tool
    orders.py             place_buy_order tool (all guardrails)
  guardrails/
    buying.py            Input guardrail (pre-flight spend cap check)
  notifications/
    email.py             SMTP email on buy / guardrail / review
  state/
    tracker.py            Spend tracker with disk persistence
tests/
  test_coinbase_auth.py
  test_coinbase_client.py
  test_tracker.py
  test_monitor_trigger.py
  test_jev_decision.py    Jev state/questions/providers/compose — keyless
```

## Guardrails

Seven independent safety checks prevent runaway spending — unchanged from the
original agent, still enforced in code inside `place_buy_order` regardless of
what Jev or the execution agent say:

| Check | Where enforced |
|---|---|
| Min / max single buy | `place_buy_order` tool + input guardrail + Jev `compose_decision` sizing |
| Daily spend cap (rolling 24 h) | `place_buy_order` tool + input guardrail + `compose_decision` caps override |
| Lifetime spend cap | `place_buy_order` tool + input guardrail + `compose_decision` caps override |
| Max buys per hour | `place_buy_order` tool + input guardrail + `compose_decision` caps override |
| USD balance check | `place_buy_order` tool + `compose_decision` balance override |
| Price drift check | `place_buy_order` tool (execution-time re-check) |
| Human approval | `place_buy_order` tool (when `REQUIRE_APPROVAL=true`) |

## Observability

- **Logs** — JSON to stdout via structlog; price checks, Jev decisions, buys, and guardrail trips are all logged
- **Traces** — OTEL spans for `price_poll`, `jev_decision`, `agent_run`, `get_current_price`, `get_account_balance`, `place_buy_order`
- **Metrics** — `price_check_total`, `buy_executed_total`, `buy_blocked_total`, `buy_amount_usd`
- **Email** — on successful buy, guardrail trip, or Jev `review` flag (requires SMTP config)

## Deployment notes

- Run as a long-lived container or systemd service.
- Mount a persistent volume at `STATE_DIR` so spend limits survive restarts.
- Use `USE_SANDBOX=true` with the Coinbase sandbox environment for testing.
- Set `OPENAI_AGENTS_DISABLE_TRACING=1` to stop the SDK from sending traces to OpenAI's platform.
- For production, inject secrets via your platform's secret management (AWS Secrets Manager, GCP Secret Manager, etc.) rather than a `.env` file.
- The Decisions API is alpha/single-provider — do not treat `openrouter` as a
  hard dependency without a fallback story; `DECISION_PROVIDER=dry-run`
  remains a safe degrade path.
