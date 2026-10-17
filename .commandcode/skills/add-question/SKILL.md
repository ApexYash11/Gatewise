---
name: add-question
description: Add or change a decision question in the versioned Gatewise question registry (noul/choice/score rules, version bump policy, benchmark implications). Use when the user wants a new question, a rubric change, or touch gatewise/decisions/questions/pull_request.yaml.
---

# Change a decision question

## Steps

1. Read `@docs/agents/questions.md` — type shapes, banding rule, versioning.
2. Edit `gatewise/decisions/questions/pull_request.yaml`; **bump `version`** on
   any rubric wording/criteria/label-set change.
3. Update `tests/unit/test_registry.py` and any fixture quoting the criteria.
4. New planner routing must be banded (`>= level`, `>= 0.5`) in
   `gatewise/actions/pipeline.py`; exact-float routing is a bug.
5. Ship via the `/ship-work` loop; `/verify` before the PR.

## Pitfalls

- Silent rubric edits — the one failure mode versioning exists to prevent.
- Naming specific questions inside `gatewise/decisions/jev.py` (provider must
  stay generic above the provider).
