# Changelog

All notable changes to Gatewise are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Gatewise is pre-1.0. `0.x` releases may change the decision schemas or the API.

## [Unreleased]

Nothing yet.

## [0.1.0]

First public release.

### Added

- **Decision layer.** Typed `DecisionProvider` abstraction with a real Jev
  implementation. No keyword-counting or heuristic fallback exists anywhere; a
  provider failure is recorded as a failure and never converted into a default
  decision.
- **Versioned question registry.** Six pull request questions
  (`pr_category`, `pr_risk`, `pr_breaking_change`, `pr_additional_testing`,
  `pr_maintainer_review`, `pr_security_review`) defined in
  `packages/decisions/questions/pull_request.yaml`, batched into one model call and
  identified as `name@version`.
- **Untrusted-input boundary.** Pull request text is structurally isolated from
  decision instructions.
- **GitHub ingestion.** Webhook signature verification and delivery
  deduplication, plus event parsing.
- **Decision pipeline and action planner.** Every path *plans* actions.
  Executing them against GitHub is a separate, explicit step requiring a token, so a
  decision never mutates a repository on its own.
- **Audit store.** SQLAlchemy models persisting runs, decisions, and planned
  actions with the question version each answer was asked under.
- **HTTP API and dashboard.** FastAPI service with the webhook receiver, read
  endpoints, and a browser UI including filter chips, a decision graph, and a
  review form.
- **Evaluation harness.** Dataset loading with enforced provenance, metrics
  (accuracy, precision, recall, F1, false positive/negative rates, Brier score,
  latency, tokens, cost), and a runner.
- **Test suite.** 248 tests across unit, integration, and adversarial suites. No
  network access required.
- **Scripts.** `scripts/serve.py`, `scripts/smoke_jev.py`, `scripts/smoke_pipeline.py`,
  `scripts/smoke_persist.py`, `scripts/seed_dashboard.py`, `scripts/review_pr.py`,
  `scripts/apply_action.py`, `scripts/compare_providers.py`,
  `scripts/run_benchmark.py`, `scripts/diagnose_jev.py`, and demo recording
  tooling.

### Known limitations

- The bundled benchmark dataset is **assistant-assessed**, not human-assessed. It
  exercises the harness; it is not evidence about decision quality. No accuracy
  claim is made.
- Action *execution* requires an explicitly configured `GITHUB_TOKEN`. The
  dashboard only ever plans actions.
- Pre-1.0: schemas and API may change.

[Unreleased]: https://github.com/ApexYash11/Gatewise/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ApexYash11/Gatewise/releases/tag/v0.1.0