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

## Four findings that shaped the design

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

This was not theoretical: the SDK's own error output during a live attempt showed
`probabilities.3.[key] Input should be a valid integer`, confirming the mismatch
empirically.

### 3. Jev is not deterministic across identical requests

Two consecutive live calls on identical context returned `pr_risk` 2.06 and 2.09,
and `pr_breaking_change` 0.38 and 0.40, while `pr_category` was identical at
confidence 1.00.

This matters for design, not just documentation:

- **Route on levels and bands, never on exact floats.** Comparing a stored `0.70`
  against a threshold of `0.70` is meaningless. `ScoreAnswer.resolve_level()` and
  noul probability bands exist for this reason.
- **The evaluation harness must tolerate this.** Accuracy and F1 are robust to it; any
  metric asserting bitwise equality of scores is not.
- **Do not treat small score deltas as signal.** A 0.03 difference between two runs is
  noise, not a change in the pull request.

### 4. Noul answers have no confidence field

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

## Transports: TypeSafe direct and OpenRouter

Both serve **the same real Jev model** — this is a routing change, not a change of
model, and never a downgrade to a substitute.

| | TypeSafe (direct) | OpenRouter |
| --- | --- | --- |
| Base URL | `https://api.typesafe.ai` | `https://openrouter.ai/api` |
| Endpoint | `POST /v1/systemone` | `POST /v1/systemone` |
| Key env var | `TYPESAFE_API_KEY` (alias `JEV_API_KEY`) | `OPENROUTER_API_KEY` |
| Model | `jev-latest` | `typesafe/jev-1.13` (alias `~typesafe/jev-latest`) |
| Context | 32,000 tokens | 32,000 tokens |
| Input price | $0.042 / 1M | $0.042 / 1M |
| Output price | $0.00 / 1M | $0.00 / 1M |
| `usage.cost` | not returned | returned (USD) |

The official TypeSafe SDK works against OpenRouter by changing the base URL; the SDK
appends `/v1/systemone`, producing `https://openrouter.ai/api/v1/systemone`. Gatewise
therefore supports both with no code duplication — only the configured base URL and
key change.

Gatewise resolves credentials with `Settings.jev_credentials()`. A direct TypeSafe
key takes precedence; otherwise an OpenRouter key switches the base URL to
`https://openrouter.ai/api`.

> Note: `client.models.list()` will fail against OpenRouter, because `GET /api/v1/models`
> returns OpenRouter's model-list shape rather than TypeSafe's, which the SDK rejects.
> Gatewise does not call it. Use the OpenRouter Models API directly instead.

### Two caveats found in the OpenRouter path

1. **Extra response fields.** OpenRouter adds `id`, `provider`, and `usage.cost`
   alongside TypeSafe's `model`, `answers`, and `usage`. Our schemas ignore unknown
   fields, and `extract_usage` captures the reported cost. Cost is left `None` when
   the provider does not report it, rather than being estimated.
2. **402 Insufficient credits.** A distinct, common failure. Gatewise maps it to an
   explicit billing message so it is never mistaken for a code defect.

## Live verification status

| Check | Result |
| --- | --- |
| `https://api.typesafe.ai/v1/models` without a key | 403 (reachable, auth required) |
| `https://openrouter.ai/api/v1/chat/completions` without a key | 401 (reachable, auth required) |
| Live `POST https://openrouter.ai/api/v1/systemone` | **200 — real decisions returned** |
| End-to-end PR evaluation via `scripts/smoke_jev.py` | **Passing** |

### A real run

Input: a simulated pull request bumping the NGINX ingress controller 4.4.0 → 4.9.0,
touching `deploy/helm/values.yaml` and a test file.

```
transport: openrouter
model:     jev-latest

pr_additional_testing      0.70
pr_breaking_change         0.40
pr_category                dependency (confidence 1.00)
pr_maintainer_review       0.53
pr_risk                    2.09 -> level 2 [Moderate. Real behavioural change
                           affecting known consumers.] (confidence 0.62)
pr_security_review         0.42
```

Two observations worth recording:

1. **The decisions are coherent.** A dependency bump classified as `dependency`
   (confidence 1.00) with a *Moderate* risk level is exactly right: not a doc change,
   not a critical one. Security review at 0.42 is also sensible, since a dependency
   bump touches the supply chain.
2. **The model is not deterministic.** A repeat run returned `pr_risk` 2.06 and
   `pr_breaking_change` 0.38 rather than 2.09 and 0.40, while `pr_category` was
   identical at confidence 1.00. Judgements are stable; exact floats are not. Anything
   comparing runs must therefore compare levels and bands, not raw numbers.

### Credential precedence gotcha

`pydantic-settings` resolves **ambient environment variables ahead of `.env`**. A
rotated key written to `.env` is therefore silently ignored while an older exported
variable remains set — which surfaced as a misleading provider error rather than a
configuration error. `scripts/diagnose_jev.py` reads `.env` first and prints the
resolved key's last four characters so this is diagnosable, and
`tests/unit/test_config.py::test_environment_variable_wins_over_dotenv` pins the
precedence rule.

## Verification status of the rest
