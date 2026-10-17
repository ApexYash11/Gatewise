# Adding or changing a decision question

The `/add-question` skill points here. The registry is
`gatewise/decisions/questions/pull_request.yaml`; every record is `name@version`.

## Question types

| Type | Shape | Rules |
|---|---|---|
| `noul` | `noul: 0..1` probability | "How likely is X" — binary judgement with a calibrated band |
| `choice` | `choice`, `probabilities` over the labels in `criteria` | Labels stay closed, but nothing in the response path validates a returned label against them |
| `score` | `score`, `legend`, `probabilities` over an ordered `criteria` list | A zero-based ordered rubric; `pr_risk` is currently 0..4. Policy reads `resolve_level()`, never exact floats |

Jev is non-deterministic: planner thresholds use bands (`>= 3`,
`>= 0.5`), and any new policy must do the same. Exact-float routing is a bug.

## Changing an existing question

A rubric edit (wording, criteria, thresholds inside the definition, label set)
**requires a version bump** (`pr_risk@1` → `@2`). Silent edits make history
incomparable — that is the one failure mode versioning exists to prevent.

- Update wording/criteria in the YAML, bump its `version`.
- The registry re-sorts; `EvaluationRun.question_versions` streams the new
  identifier from the next run onward. Old audit rows keep their old versions.
- Update `tests/unit/test_registry.py` (identifiers, types, validation rules)
  and any fixture that quotes the changed criteria verbatim.

## Adding a question

1. Decide type first (`noul` for a likelihood, `choice` for a category, `score`
   for a zero-based ordered rubric — `pr_risk` is 0..4 today).
2. Write instructions as a single explicit ask; put the decision rule the model
   should apply into `criteria`.
3. Add the question to the YAML. `gatewise/decisions/jev.py` stays generic: the
   provider batches whatever the registry supplies, so nothing there names a
   specific question. The six-question expectation lives in the tests — update
   the fixtures and assertions that count questions instead.
4. If the planner (`gatewise/actions/pipeline.py`) should route on it, add a
   *banded* rule; otherwise routing stays policy-free.
5. Tests: registry validation (`test_registry.py`),
   provider-compatible request shape (`test_jev_provider.py`), planner band
   behavior (`test_pipeline_run.py`).

## Benchmark implications

`benchmarks/pr_triage_seed.json` is `label_source: "assistant"` and must never
be cited as accuracy. A question change invalidates the comparability of domain
metrics on the seed set; note that in the PR and see `distribution.md` for the
human-labelled dataset plan (issue #7).
