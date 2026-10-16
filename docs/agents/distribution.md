# Distribution surfaces of Gatewise

How Gatewise reaches users: four installable surfaces, one decision layer. The
`/ship-work` skill's phase map points here for surface details.

## Surfaces

| Surface | Install | Status | Issue |
|---|---|---|---|
| PyPI CLI `gatewise` | `gatewise review owner/name 123` | shipped (in-repo, unpublishable yet) | #2 (merged) |
| PyPI package `pip install gatewise` | needed for the CLI to be a real download | planned | #4 |
| GitHub Action | one workflow YAML + secret per repo | planned | #6 |
| npm skill/plugin for coding agents | `cmd skills add ApexYash11/Gatewise` style | planned | #5 |
| Human-labelled evaluation dataset | evidence, not an install | parallel | #7 |

## Blocking constraint for publishing

`packages/*` install as top-level import names (`github`, `actions`, `config`).
`github` already exists on PyPI — **the namespace rename to `gatewise.*`
(phase 1, issue #4) is the gate for every publish step**. Do not publish
anything to a public registry before it lands.

## Invariants for every surface

- Same loop as the webhook path — `packages/review/run_review` is the single
  serverless entry; a new surface wraps it, never reimplements it.
- Fail loud: model unavailability surfaces as a failed run (CLI exit 3 /
  commented failure), never a default verdict.
- Secrets flow via environment/workflow secrets only; never baked into
  artifacts; the CLI gives `exit 5` with the explanatory message when none are
  configured.
- CI consumers declare least privilege (`pull-requests: write`,
  `issues: write`, `contents: read`).

## GitHub Action shape (phase 2)

`action.yml` at the repo root calling `gatewise review $GITHUB_REPOSITORY $PR`;
posts/updates one triage comment (renderer in `packages/review/render.py` is
the shared report so it is not a separate codebase); applies the planned
actions only. Composite or docker run wrapping the Phase-1 wheel.

## npm skill shape (phase 3)

First shape: skills package (SKILL.md + `{COMMANDCODE_SKILL_DIR}`-relative
usages) telling an agent to run the `gatewise` CLI — triage before reading
files. Later shape: a thin MCP server wrapping `review`/`plan` as tools.
Author via the bundled `skill-builder` skill, then distribute.

## Dataset (phase 4)

Hand-label 30–50 public PRs across the six questions, `label_source: "human"`;
extend the harness report to a seed-vs-human table. Until that exists, no
accuracy claims anywhere — the honest framing ship texts must keep.
