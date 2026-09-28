# 1. Isolate the decision provider behind an abstract interface

- Status: accepted
- Date: 2026-09-28

## Context

Gatewise's entire premise is that its intelligence comes from a real typed decision
model (TypeSafe AI's Jev), and that the product should not be coupled to any one
provider. The specification requires a `DecisionProvider` abstraction so that a
different provider can be introduced later without rewriting the product.

There is a real risk here beyond ordinary coupling. Because decision logic is
"just" a mapping from context to a label, it is tempting to implement a fallback that
counts risk keywords and produces a plausible-looking score when the model is
unavailable. Such a fallback is indistinguishable from the real thing at the call
site, and a downstream action triggered by it would be unauditable in substance while
looking perfectly auditable in form. The specification names this as the central
prohibition: no mock decision engine.

## Decision

1. `DecisionProvider` is an abstract base class exposing `evaluate(state, questions)`
   and a `model` property. All higher layers depend only on this.
2. `JevDecisionProvider` is the sole implementation. Its network access is confined to
   `evaluate()`.
3. There is **no** rule-based, heuristic, or keyword-based provider, and none may be
   added as a fallback. A missing API key raises at configuration time
   (`Settings.require_jev_key`) and the provider constructor rejects an empty key.
4. Provider failures raise `DecisionUnavailable` (retryable/environmental) or
   `DecisionValidationError` (bad response). Neither is ever converted into a
   default answer.
5. Tests inject at the HTTP transport layer, asserting on request construction and
   response normalization. They do not simulate model judgement.

## Consequences

- The product cannot degrade to fake intelligence, because no such code path exists.
- A genuinely unavailable decision is a visible, recorded failure rather than a
  quiet low-risk verdict. This is the correct trade: false "safe" outcomes are far
  more damaging than a failed triage.
- Adding a future provider is a contained change: implement the interface, register
  it, and the benchmark harness can compare it against Jev on the same dataset.
- The abstraction is not speculative generality, since a second provider is already
  contemplated by the evaluation requirements.
- Billing failures (OpenRouter `402`) are mapped to an explicit, actionable message
  rather than a generic API error, so an unfunded account is never mistaken for a
  code defect.

## Update: OpenRouter transport (2026-09-28)

TypeSafe publishes Jev on OpenRouter as `typesafe/jev-1.13` (alias
`~typesafe/jev-latest`) at identical pricing, context length, and API shape. This is
**not** an alternative model — it is the same real Jev model behind a different host.

This changes nothing about the decision above. A base URL and an API key are
configuration, not logic, so OpenRouter support is implemented as transport
resolution in `Settings.jev_credentials()` rather than as a second provider class.
Creating an `OpenRouterDecisionProvider` would have been the wrong move: it would
duplicate the normalization and failure-mapping logic while implying the two are
different decision systems, which would corrupt any later provider comparison in the
evaluation harness.

The distinction this guards against is easy to blur: a **transport** is *how* the same
model is reached; a **provider** is *which* model answers. Only the latter may be
varied for comparative measurement.
