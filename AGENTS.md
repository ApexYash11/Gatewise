# AGENTS.md

Rules for coding agents working on Gatewise. Read this first; the detailed
playbooks load on demand (see "Skill index" at the end).

## Project

Gatewise is a decision layer for autonomous software engineering: it extracts a
compact context from a pull request, asks a typed decision model (Jev) six
versioned questions, and turns typed answers into actions. It is **not** a code
reviewer and **not** a chatbot. Package map:

- `gatewise/decisions/` — typed schemas, provider abstraction, Jev provider, versioned question registry
- `gatewise/context/` — context builder; untrusted PR text is isolated here
- `gatewise/github/` — webhook signature verification, dedup, event parsing, fetching
- `gatewise/actions/` — decision pipeline, action planner, GitHub executor
- `gatewise/audit/` — SQLAlchemy audit store
- `gatewise/review/` — serverless review loop and the `gatewise` CLI
- `gatewise/evaluation/` — dataset loading with provenance, metrics, benchmark runner
- `gatewise/config/` — environment settings; secrets never leave here
- `apps/api/` — FastAPI: webhook receiver, read endpoints, dashboard

## Commands

Run these **before** claiming any change is green (test first, report after):

- Install: `python -m venv .venv` + `pip install -e ".[dev]"`
- Tests: `python -m pytest -q` against a `.[dev]` install — full suite, no
  network, no API key; `python -m ruff check .` and `python -m mypy` beside it
- Lint: `ruff check .` · Types: `mypy`
- Server + dashboard: `python scripts/serve.py`

## Architecture boundaries

1. **Fail closed, never fake.** No heuristic fallback exists anywhere. A provider
   failure is recorded as a failure; a missing decision authorizes nothing and is
   never turned into `risk = 0` or `safe = true`.
2. **Untrusted input is untrusted.** Attacker-controlled PR text lives in
   `untrusted_content`, separate from trusted metadata (`gatewise.context`).
3. **Webhook order is a security property:** verify signature → deduplicate →
   parse. Never reorder.
4. **Actions are planned on every path; executed only deliberately.** Execution
   requires a token and only via the executor allowlist
   (`add_label`, `comment`, `request_review`, `trigger_workflow`); `merge`,
   `delete`, `force_push`, `release`, `deployment` are never performed.
5. **Decisions are `name@version`.** Changing a rubric requires a version bump;
   silent edits make history incomparable.
6. **Provider-independent above the provider.** Everything depends on the
   abstract `DecisionProvider`, never Jev specifics.

## Coding standards

- Python 3.12+, complete annotations, no bare `except`.
- Comment only to record a constraint, invariant, or tradeoff a reader could not
  infer — never narrate code. Model docstrings on `gatewise/review/loop.py`.
- Line length 100 (`ruff` enforces). Imports ordered (ruff `I` rules).
- Keep diffs minimal: fix the problem asked for, don't reformat around it.

## Testing standards

- Stub the **network boundary** only — never the model's judgement. No test may
  hard-code "this PR is high risk" from a heuristic.
- Test location mirrors source (`github/fetch.py` → `test_fetch.py`).
- pytest-asyncio is auto-mode. Parametrize similar cases instead of copy-pasting.
- Any change to the untrusted-input surface gets `tests/adversarial/` coverage.
- A failing behavior gets a test that fails without the fix.

## Security model

- Secrets are never logged, echoed, committed, or sent to the model. `.env` and
  `*.db`/keys must never be committed (CI `guard` job enforces).
- PR text is attacker-controlled: treat every prompt-injection report seriously
  (`tests/adversarial/`).
- Report vulnerabilities via SECURITY.md, never a public issue.

## Commits and PRs

Standing loop: raise the phase/task as a GitHub issue (`enhancement`/`bug`
label) → new branch `feat/<short-name>` → implement → verify → commit (message
closes the issue) → push → PR with *What / Review guide / Test evidence* →
**merge only after the user's review**. A breaking point is reported as its own
issue and worked to a fix. Never merge to `main` without approval.

## Boundaries

**Ask first:** destructive git/file operations, new dependencies, changes to
decision schemas or the webhook pipeline, anything touching tokens/secrets.

**Never:** fake intelligence or substitute decisions; commit secrets,
databases, media binaries; reorder webhook steps; disable security tests;
`git add -A` blindly (local agent state under `.commandcode/` stays untracked).

## Skill index

Load the playbook for the task at hand:

- Pre-merge check → run `/verify`
- Reviewing a PR in this repo → `/gatewise-review` (playbook: `docs/agents/reviews.md`)
- Branch/issue/PR workflow → `/ship-work` (playbook: `docs/agents/shipping.md`)
- Adding or changing a decision question → `/add-question` (playbook:
  `docs/agents/questions.md`)
- Distribution surfaces → `docs/agents/distribution.md`
