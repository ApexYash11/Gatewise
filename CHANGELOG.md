# Changelog

All notable changes to Gatewise are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Gatewise is pre-1.0. `0.x` releases may change the decision schemas or the API.

## [Unreleased]

### Added

- **`gatewise.*` namespace (breaking; the gate for PyPI).** The packages used
  to install as top-level import names (`github`, `actions`, `config`, ...),
  which collide with existing PyPI packages; everything now installs and
  imports under `gatewise.*` (`gatewise.decisions`, `gatewise.review`, ...).
  The package version moves to `0.2.0` accordingly, while decision records
  keep their own `name@version` identity.
- **Release workflow.** Builds the sdist and wheel, installs the wheel into
  a clean environment, smoke-imports the package and CLI, and publishes on
  `v*` tags via GitHub Actions trusted publishing (no PyPI token stored in
  the repository).
- **`gatewise` CLI.** `gatewise.review` provides the serverless review loop —
  `gatewise review owner/name 123` fetches a real pull request, asks the
  decision model, records every decision evaluation (once the pull request
  has been fetched and the provider is configured), and performs only the
  actions it justifies, with the same result a webhook delivery produces.
  `--no-execute` plans and records without touching GitHub (reads may still
  be authenticated, so private repositories stay reviewable). Performed and
  skipped actions for the same content are never performed again; plan-only
  and failed rows stay claimable by a later run. Stable exit codes for
  automation: 0 reviewed, 2 usage, 3 decision/model failure, 4 fetch failed,
  5 not configured, 6 action execution failed.
- **Action claims are now execution-state-aware.** Action identity includes the
  target and the head commit (distinct labels never collide; a new head commit
  re-justifies actions), and performing an action is decided by an atomic
  claim in the audit store with per-row execution status: performed and skipped
  actions never repeat, failed ones are retried on a later run, and concurrent
  reviews cannot double-perform the same action. Claims carry a token, so a
  reclaimed stale claim can never settle an outcome onto the newer claim.
- **Linting in CI.** `ruff` and `mypy` over all packages, run as a new CI job.
- **`derived` label source.** Labels borrowed from another human process (for
  example maintainer-applied GitHub labels) are now a distinct `label_source`:
  human-produced, but not annotated against Gatewise's question rubrics, so they
  never count as human-validated accuracy.
- **A second evaluation dataset** covering only `pr_category`:
  `benchmarks/pr_triage_cpython_labels.json` (24 CPython pull requests labelled by
  CPython maintainers, `label_source: "derived"`). It exercises the harness
  against real pull requests and is **not** evidence about decision quality.
  Regenerate it with `scripts/fetch_github_label_dataset.py`.

### Changed

- **Choice and score questions report accuracy only.** `pr_category` (one chosen
  label) and `pr_risk` (an ordered level) have no true/false-positive split, so
  precision/recall/F1 are reported for binary questions only. The previous
  treatment counted every miss as a false negative, which made those numbers
  meaningless.
- **Ruff ignores `.commandcode/`.** That directory is untracked local agent
  scratch space, not project source.

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