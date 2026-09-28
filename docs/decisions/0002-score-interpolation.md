# 2. Keep both the raw score and a discrete level

- Status: accepted
- Date: 2026-09-28

## Context

The specification defines risk as a bounded 1-5 judgement and states: *"Do NOT
interpolate arbitrary numeric values."* Its own examples, however, display
`Risk 4.1 / 5` and `4.2`, which are interpolated. These cannot both hold.

The verified Jev contract resolves the ambiguity. `ScoreAnswer.score` is documented
as *"Expected score: the probability-weighted average of the rubric levels. May fall
between integer levels"*, and published examples return `1.84` and `1.04` on
three-level rubrics. The model also returns a full per-level probability
distribution. Interpolation is therefore not an approximation Gatewise introduced; it
is what the model actually computes, and rounding it away would discard information
the provider deliberately produced.

## Decision

`ScoreAnswer` stores both:

- `score` — the raw expected value returned by the model, unmodified.
- `resolve_level()` — the discrete arg-max level, derived from the per-level
  probabilities (falling back to rounding the expected value if probabilities are
  absent).

Policy code routes on `level`; the dashboard and audit log display `score`. Neither
value is ever invented.

## Consequences

- The intent of the original constraint is honoured: action selection is driven by a
  stable, discrete, auditable level, not by a fuzzy float compared against an
  arbitrary threshold.
- No model signal is lost, so the evaluation harness can later test whether routing on
  the interpolated value would have been better than routing on the arg-max level.
  That is a measurable question, and answering it needs both numbers.
- Thresholds in policy code read as `risk >= 3`, not `risk > 3.7`, which is easier to
  review and to change.
- `resolve_level()` mutates and caches `level`, so it is not a pure function. It is
  idempotent, and callers should treat the answer object as owned by the run that
  produced it.
