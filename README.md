# Gatewise

Decision infrastructure for autonomous software engineering, built on typed
System-1 decision models.

Gatewise sits between AI coding agents / GitHub events and engineering actions. It
extracts a compact context from a pull request, asks a real decision model for typed
answers, and lets application policy decide what to do with them.

> **Status: pre-MVP.** The decision layer, versioned question registry,
> untrusted-input boundary, GitHub webhook verification, the decision pipeline,
> persistence, the HTTP API, and the evaluation harness are implemented and tested
> (188 tests). Action *execution* against GitHub and the dashboard are not built
> yet.
>
> **Live API status: blocked on credentials.** Gatewise previously made real calls
> to TypeSafe's Jev via OpenRouter and recorded real typed decisions; the
> configured key has since expired (`401 API key expired`). Set
> `OPENROUTER_API_KEY` or `TYPESAFE_API_KEY` to resume. No code in this repository
> simulates or substitutes for a model response.

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
pytest                                  # 247 tests, no network access required
python scripts/serve.py                 # API + dashboard on http://127.0.0.1:8000
python scripts/smoke_jev.py             # one real call: context -> six decisions
python scripts/smoke_pipeline.py        # full pipeline, real model, action plan
python scripts/smoke_persist.py         # context -> model -> SQLite, read back
python scripts/seed_dashboard.py        # evaluate real PRs to fill the dashboard
python scripts/review_pr.py owner/name 1 # evaluate one real PR and label it
python scripts/compare_providers.py     # compare providers over a dataset
python scripts/run_benchmark.py         # evaluation harness over a labelled dataset
python scripts/diagnose_jev.py          # print the resolved credential source
```

## Evaluation

The harness scores a provider against labelled pull requests and reports
accuracy, precision, recall, F1, false positive/negative rates, Brier score,
latency, tokens, and cost. See [docs/evaluation/README.md](docs/evaluation/README.md).

The bundled dataset uses **assistant-assessed** labels and is a smoke test for the
harness, not evidence about decision quality. A human-labelled dataset of at least
30 cases is still needed before any accuracy claim is meaningful.

`smoke_jev.py` exits `0` on success, `2` when no key is configured, and `3` when
the decision is unavailable (for example, insufficient credits).

The test suite stubs only the HTTP transport. It never simulates model judgement.

## Running the API

One command. It loads `.env`, creates the database if missing, and serves the API
and dashboard together:

```bash
.venv\Scripts\python scripts\serve.py
```

Then open **http://127.0.0.1:8000**

Add `--open` to launch a browser, `--reload` for development.

The script checks configuration before starting and names any missing variable.
That matters because the failure mode is otherwise confusing: without a key the
server still starts and answers every request, but evaluations return `503
decision provider is not configured` and the dashboard stays empty.

### Manual invocation

If you prefer to run uvicorn directly:

```bash
set OPENROUTER_API_KEY=sk-...        # or TYPESAFE_API_KEY
set GITHUB_WEBHOOK_SECRET=...         # required for webhook deliveries
set DATABASE_URL=sqlite+aiosqlite:///./gatewise.db
set PYTHONPATH=packages;apps/api
python -m uvicorn app.main:app --port 8000
```

### Filling the dashboard

An empty database renders *"No evaluations yet"* by design. There are two ways to
populate it, both with real decisions from real pull requests.

**From the browser.** The dashboard has a review form: enter `owner/name` and a
pull request number, and it fetches that pull request from GitHub, asks Jev the six
questions, and files the result in the index. This is the quickest path and needs
no terminal.

**From the terminal**, which additionally applies the actions:

```bash
.venv\Scripts\python scripts\seed_dashboard.py     # six public PRs
.venv\Scripts\python scripts\review_pr.py ApexYash11/Gatewise 1
```

`review_pr.py` fetches a real pull request, evaluates it, records the run, and
applies the actions it justified. Fetch is unauthenticated for public
repositories; only the labelling step needs `GITHUB_TOKEN`.

Set `GITHUB_TOKEN` to review private repositories or to avoid GitHub's
unauthenticated rate limit. The browser form only ever *plans* actions; it never
writes to GitHub, so a click in a page cannot modify a repository.

| Endpoint | Purpose |
| --- | --- |
| `GET /` | The dashboard, with the review form. |
| `GET /api/health` | Configuration state. Never calls the model. |
| `GET /api/pull-requests` | Evaluated pull requests, newest first. |
| `GET /api/pull-requests/{id}` | One pull request with its runs. |
| `GET /api/pull-requests/{id}/decisions` | Decisions for the latest run. |
| `GET /api/pull-requests/{id}/graph` | The decision path, for the graph view. |
| `GET /api/decisions` | Recent decisions across all pull requests. |
| `POST /api/reviews` | Fetch, evaluate, and record a real pull request now. |
| `POST /webhooks/github` | Signed pull request delivery. |
| `POST /internal/decisions/evaluate` | Ad-hoc evaluation without a webhook. |
| `GET /docs` | Interactive OpenAPI documentation. |

## Repository layout

```
packages/decisions/   Typed schemas, provider abstraction, Jev provider, registry
packages/context/     PR context builder and untrusted-input handling
packages/config/      Environment configuration and secret handling
packages/github/      Webhook signature verification, deduplication, event parsing
packages/actions/     Decision pipeline and deterministic action planning
packages/audit/       SQLAlchemy models and the audit store
packages/evaluation/  Dataset loading with enforced provenance, metrics, runner
apps/api/             FastAPI service: webhook receiver and read endpoints
benchmarks/           Seed benchmark dataset (assistant-assessed labels)
tests/unit/           Schemas, registry, configuration, webhook security, dedup,
                      metrics, dataset, evaluation runner
tests/integration/    Provider, pipeline, webhook flow, persistence, HTTP API
tests/adversarial/    Prompt-injection and untrusted-input cases
docs/architecture/    Overview and the verified Jev API contract
docs/decisions/       Architectural decision records
docs/evaluation/      How the harness scores and what the dataset can support
```

## Research question

> Can a fast typed decision model serve as a reliable decision layer for autonomous
> software engineering workflows?

This is an experiment, and it is measured rather than asserted. The evaluation
framework and benchmark dataset are specified but not yet built; no accuracy or
cost claim is made here, because none has been measured.

## License

Apache-2.0. See [LICENSE](LICENSE).
