# Gatewise

Decision infrastructure for autonomous software engineering, built on typed
System-1 decision models.

Gatewise sits between AI coding agents / GitHub events and engineering actions. It
extracts a compact context from a pull request, asks a real decision model for typed
answers, and lets application policy decide what to do with them.

> **Status: pre-MVP.** The decision layer, versioned question registry,
> untrusted-input boundary, GitHub webhook verification, the decision pipeline,
> persistence, and the HTTP API are implemented and tested (158 tests).
> Action *execution* against GitHub, the dashboard, and the evaluation harness are
> not built yet.
>
> **Live API status: working.** Gatewise serves real calls to TypeSafe's Jev
> model via OpenRouter and records real typed decisions. See
> [docs/architecture/jev-contract.md](docs/architecture/jev-contract.md) for a
> sample run. No code in this repository simulates or substitutes for that
> response.

## Why this exists

Gatewise is not a code reviewer and not a chatbot. It is a decision layer. The
intelligence is a fast typed decision model (TypeSafe AI's **Jev**, a System-1 model
trained with Reinforcement Learning for Calibrated Decisions); the application merely
translates those typed judgments into actions.

Three rules follow from that, and they shape the whole codebase:

1. **No mock decision engine.** There is no keyword-counting fallback anywhere. If the
   model is unavailable, the run fails and is recorded. A missing decision is never
   converted into `risk = 0` or `safe = true`.
2. **Provider-independent.** Everything above the provider depends on the abstract
   `DecisionProvider`, not on Jev.
3. **Untrusted input is untrusted.** Pull request text is attacker-controlled and is
   structurally isolated from decision instructions.

## Architecture

```
GitHub Event
     ↓
Webhook (signature verified, deduplicated)      [not yet built]
     ↓
Context Builder  ── isolates untrusted text
     ↓
DecisionProvider ── JevDecisionProvider
     ↓
Decision Registry ── versioned questions
     ↓
Action Router                                      [not yet built]
     ↓
Audit Store                                        [not yet built]
```

See [docs/architecture/overview.md](docs/architecture/overview.md).

## The decisions

Six versioned questions, batched into a single Jev call:

| Question | Type | Meaning |
| --- | --- | --- |
| `pr_category` | choice | bug, feature, refactor, documentation, test, dependency, security, infrastructure, other |
| `pr_risk` | score | 5-level rubric, trivial → critical |
| `pr_breaking_change` | noul | likely to break existing consumers |
| `pr_additional_testing` | noul | warrants testing beyond the normal path |
| `pr_maintainer_review` | noul | requires maintainer review before merge |
| `pr_security_review` | noul | affects security or trust boundaries |

Definitions live in [`packages/decisions/questions/pull_request.yaml`](packages/decisions/questions/pull_request.yaml).

## Setup

Requires Python 3.12+.

```bash
git clone https://github.com/ApexYash11/Gatewise.git
cd Gatewise
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and set an API key. Two supported transports, both
serving **the same real Jev model**:

```bash
# Option A - OpenRouter (TypeSafe publishes Jev here; same model, same API shape)
OPENROUTER_API_KEY=sk-or-...

# Option B - direct from TypeSafe
TYPESAFE_API_KEY=sk-...
```

If both are set, the direct TypeSafe key wins. The key is never committed, never
logged, and never sent to the model.

```bash
pytest                                  # 158 tests, no network access required
python scripts/smoke_jev.py             # one real call: context -> six decisions
python scripts/smoke_pipeline.py        # full pipeline, real model, action plan
python scripts/diagnose_jev.py          # print the resolved credential source
```

`smoke_jev.py` exits `0` on success, `2` when no key is configured, and `3` when
the decision is unavailable (for example, insufficient credits).

The test suite stubs only the HTTP transport. It never simulates model judgement.

## Running the API

```bash
# Required
set TYPESAFE_API_KEY=sk-...            # or OPENROUTER_API_KEY for the same Jev model
set GITHUB_WEBHOOK_SECRET=...          # the webhook receives signed deliveries only
set DATABASE_URL=sqlite+aiosqlite:///./gatewise.db

set PYTHONPATH=packages;apps/api
python -m uvicorn app.main:app --port 8000
```

Interactive API docs are then at <http://localhost:8000/docs>.

| Endpoint | Purpose |
| --- | --- |
| `POST /webhooks/github` | Signed pull request delivery. Verifies the signature before parsing. |
| `GET /api/health` | Configuration state only. Never calls the model. |
| `GET /api/pull-requests` | Evaluated pull requests, newest first. |
| `GET /api/pull-requests/{id}` | One pull request with its runs. |
| `GET /api/pull-requests/{id}/decisions` | Decisions for the latest run, with question versions. |
| `GET /api/decisions` | Recent decisions across all pull requests. |
| `POST /internal/decisions/evaluate` | Ad-hoc evaluation without a webhook. |

Try it end to end against a running server:

```bash
set GITHUB_WEBHOOK_SECRET=...
python scripts/send_test_webhook.py http://127.0.0.1:8000
```

The script signs the payload, so the server performs a genuine signature check.

## Repository layout

```
packages/decisions/   Typed schemas, provider abstraction, Jev provider, registry
packages/context/     PR context builder and untrusted-input handling
packages/config/      Environment configuration and secret handling
packages/github/      Webhook signature verification, deduplication, event parsing
packages/actions/     Decision pipeline and deterministic action planning
packages/audit/       SQLAlchemy models and the audit store
apps/api/             FastAPI service: webhook receiver and read endpoints
tests/unit/           Schemas, registry, configuration, webhook security, dedup
tests/integration/    Provider, pipeline, webhook flow, persistence, HTTP API
tests/adversarial/    Prompt-injection and untrusted-input cases
docs/architecture/    Overview and the verified Jev API contract
docs/decisions/       Architectural decision records
```

## Research question

> Can a fast typed decision model serve as a reliable decision layer for autonomous
> software engineering workflows?

This is an experiment, and it is measured rather than asserted. The evaluation
framework and benchmark dataset are specified but not yet built; no accuracy or
cost claim is made here, because none has been measured.

## License

Apache-2.0. See [LICENSE](LICENSE).
