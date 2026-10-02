# Contributing to Gatewise

Thanks for your interest. This document is short on purpose — it explains the one
rule that matters, how to get set up, and what a good pull request looks like.

- [Security issues](#reporting-security-issues) — report these privately, not as issues.
- [Changelog](CHANGELOG.md) — add an entry under `Unreleased` for user-visible changes.

## The one rule that matters

**Never fake intelligence.** No rule-based, keyword-counting, or heuristic stand-in for
the decision model may be added to this repository, and no provider failure may be
converted into a default answer such as `risk = 0` or `safe = true`.

This is not stylistic. Gatewise's entire value is that a decision is a real, typed,
auditable model output. A fake fallback is indistinguishable from a real one at the
call site, so it converts a visible failure into an invisible, unauditable wrong
answer. When a decision cannot be obtained, record the failure and move on.

If an external dependency is unavailable, stop at that boundary and report the
blocker.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env      # then fill in TYPESAFE_API_KEY
pytest
```

## Secrets

- Never commit `.env`, API keys, GitHub tokens, or private keys. `.gitignore` covers
  them; do not defeat it.
- `Settings.safe_summary()` reports configuration *presence* only. Keep it that way —
  it exists so startup logs are useful without leaking values.
- Never forward credentials into model context.

## Working on decisions

Decisions are versioned artifacts in
`packages/decisions/questions/pull_request.yaml`, identified as `name@version`.

**Changing a rubric changes the meaning of every stored answer.** Bump the version.
A silent edit makes historical results quietly incomparable, which is the one failure
mode versioning exists to prevent.

## Verifying external contracts

Do not invent APIs and do not trust third-party blog posts or SEO pages about Jev —
there are many unrelated ones. Verify against, in order of preference:

1. The installed SDK source (`typesafe_sdk/`).
2. A first-party integration such as Cloudflare Workers AI or Pydantic AI.
3. A live request, once an API key is available.

When you verify a contract, record it in
the provider module docstring, with its provenance and date.

## Testing

```bash
pytest                            # everything; no network needed
pytest tests/unit                 # fast
pytest tests/adversarial          # injection and untrusted input
```

Tests must stub the **network boundary**, not the model's judgement. Assert that
Gatewise builds a correct request and handles a correct response faithfully. A test
that hard-codes "this PR is high risk" is simulating intelligence, and does not
belong here.

Every provider failure mode must be covered: timeout, rate limit, authentication,
network error, malformed response, and missing answer.

## Style

- Small, focused commits with working tests.
- Document architectural decisions in the module docstring when a choice is
  non-obvious or constrains future work.
- Prefer simple, observable, reproducible code over premature abstraction.
- Do not claim functionality that has not been tested. If something is unverified,
  say so in the README and in the relevant doc.

## Reporting security issues

Please do not open a public issue for a security vulnerability. Report it privately to
the maintainers.
