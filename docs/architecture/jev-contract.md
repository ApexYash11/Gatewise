# The verified TypeSafe AI Jev API contract

**Status: verified 2026-09-28 against `typesafe-sdk==0.7.2`.**

This document exists so that no one has to guess the external contract. Every claim
below was read out of the installed SDK package or a working HTTP request, not from
marketing copy.

## Provenance

Jev is a real product. It is TypeSafe AI's "System One" model, trained with
Reinforcement Learning for Calibrated Decisions (RLCD), and documented at
<https://typesafe.ai>. The contract below was confirmed three ways:

1. By installing `typesafe-sdk==0.7.2` and reading `typesafe_sdk/_core/constants.py`,
   `question_types.py`, `response_types.py`, `config.py`, `client/aio/client.py`, and
   `errors.py` directly.
2. Against Cloudflare's Workers AI integration of `typesafe/jev`.
3. Against Pydantic AI's `TypeSafeModel` / `TypeSafeProvider` integration.

Ad-hoc search results for "jev api" are dominated by unrelated SEO domains. Do not
trust them; use the sources above.

## Transport

| Property | Value |
| --- | --- |
| Base URL | `https://api.typesafe.ai` |
| Decision endpoint | `POST /v1/systemone` |
| Model listing | `GET /v1/models` |
| Auth | `Authorization` header |
| Timeout | 10s default |

Environment variables read by the SDK:

- `TYPESAFE_API_KEY` — required
- `TYPESAFE_DEFAULT_MODEL` — defaults to `jev-latest`
- `TYPESAFE_BASE_URL` — defaults to `https://api.typesafe.ai`

> **Naming.** The original specification called this `JEV_API_KEY`. The SDK does not
> read that name, so relying on it alone would leave the client silently
> unauthenticated. Gatewise accepts both and treats `TYPESAFE_API_KEY` as canonical.

## Request

```json
{
  "state": { "...": "any JSON value" },
  "model": "jev-latest",
  "questions": { "<name>": { "type": "noul|choice|score", "...": "..." } }
}
```

`state` may be a string or any JSON structure. `questions` is a map of names to
questions; **all compatible questions are sent in a single request**, which Gatewise
does.

### Question types

```jsonc
// noul -- probabilistic boolean. `criteria` is optional.
{ "type": "noul", "instructions": "Does this break consumers?",
  "criteria": { "true": "...", "false": "..." } }

// choice -- closed set. `criteria` is REQUIRED (a name -> description map).
{ "type": "choice", "instructions": "What kind of change is this?",
  "criteria": { "bug": "...", "feature": "..." } }

// score -- ordered rubric. `criteria` is REQUIRED (an ordered list; index 0 is lowest).
{ "type": "score", "instructions": "How risky is this?",
  "criteria": ["Trivial", "Low", "Moderate", "High", "Critical"] }
```

## Response

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "is_urgent":  { "type": "noul",  "noul": 0.95 },
    "department": { "type": "choice", "choice": "billing", "confidence": 0.8,
                    "probabilities": { "billing": 0.87, "sales": 0, "technical": 0.13 } },
    "risk_level": { "type": "score",  "score": 1.84, "confidence": 0.77,
                    "legend": { "0": "Low risk", "1": "Moderate risk", "2": "High risk" },
                    "probabilities": { "0": 0, "1": 0.16, "2": 0.84 } }
  },
  "usage": { "input_tokens": 421, "output_tokens": 36 }
}
```

## Three findings that shaped the design

### 1. `score` is interpolated, and that is correct

The SDK describes `ScoreAnswer.score` as *"Expected score: the probability-weighted
average of the rubric levels. May fall between integer levels."* Published examples
return `1.84` and `1.04` for three-level rubrics.

The specification said *"Do NOT interpolate arbitrary numeric values"* while also
showing `Risk 4.1` in its own examples — the two cannot both hold. The resolution
Gatewise adopts keeps **both** values:

- `ScoreAnswer.score` — the raw expected value from the model.
- `ScoreAnswer.resolve_level()` — the discrete arg-max level, which is what policy
  code routes on.

This honours the intent of the constraint (a stable, auditable level for action
selection) without discarding real model signal or fabricating a number.

### 2. `legend` and `probabilities` are `dict[int, ...]` but arrive as string keys

The SDK types these maps with integer keys, yet JSON object keys are always strings.
Re-hydrating a stored score answer therefore fails validation. Gatewise normalizes
keys to strings once, at the provider boundary, in
`decisions.schemas.normalize_score_levels`.

### 3. Noul answers have no confidence field

`NoulAnswer` is `{ "type": "noul", "noul": <float> }` — nothing else. There is no
separate confidence value, so Gatewise does not manufacture one. A test asserts the
attribute is absent, to keep it that way.

## Failure modes

The SDK raises a typed hierarchy that Gatewise maps onto two outcomes:

| SDK exception | Gatewise raises |
| --- | --- |
| `TypeSafeAuthenticationError` | `DecisionUnavailable` (names `TYPESAFE_API_KEY`) |
| `TypeSafeRateLimitError` | `DecisionUnavailable` |
| `TypeSafeAPITimeoutError` | `DecisionUnavailable` |
| `TypeSafeAPIConnectionError` | `DecisionUnavailable` |
| `TypeSafeAPIResponseValidationError` | `DecisionValidationError` |
| `TypeSafeAPIError` (other) | `DecisionUnavailable` |

Both are fail-closed. Callers must record the failure and skip risky actions. A
missing decision is never coerced into `risk = 0` or `safe = true`.

## Pricing and reachability

- Input: $0.042 / 1M tokens. Output: $0.00 / 1M. (Cloudflare Workers AI listing.)
- `GET https://api.typesafe.ai/v1/models` returns **HTTP 403** without credentials,
  confirming the endpoint is reachable and simply requires an API key.

## Verification status

| Check | Status |
| --- | --- |
| Contract read from installed SDK | Done |
| Request shape asserted in tests | Done (`test_request_matches_the_verified_jev_contract`) |
| Response normalization tested | Done |
| All failure paths tested | Done |
| **Live call against the real API** | **Blocked — no API key available** |
