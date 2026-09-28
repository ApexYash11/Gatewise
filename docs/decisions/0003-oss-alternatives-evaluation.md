# 3. Open-source Jev-alike projects: evaluated, not adopted as the primary provider

- Status: accepted (with a revisit trigger)
- Date: 2026-09-28

## Context

A DataCamp article, "Top 7 Open-Source TypeSafe Jev Alternatives", lists seven
projects claiming to reproduce Jev's approach locally: Laya, Nimble, Kev, SemIf,
Rizzo Flow, Von, and NanoJev. The obvious question is whether Gatewise should adopt
one, given that reaching the hosted Jev key requires paid credits.

Each of these would be a change of *provider*, not merely transport, so the decision
was evaluated on evidence rather than enthusiasm.

## What was verified

All named repositories were checked directly via the GitHub API, and model weights
were checked on Hugging Face:

| Project | Repo | Created | Weights |
| --- | --- | --- | --- |
| Kev | `jaredpalmer/kev` (7.6k stars) | 2026-09-17 | Yes — 0.8B/4B/9B/27B on Qwen3.5 |
| Laya | `mizorewww/laya-mlx` (6.5k stars) | 2026-09-19 | Yes — MLX runtime |
| SemIf | `TheoLeeCJ/SemIf-OpenJev` (4.5k stars) | 2026-09-16 | Not located under a matching name |
| NanoJev | `TianyuCodings/NanoJev` (2.4k stars) | 2026-09-17 | Yes |
| Rizzo Flow | `Rizzo-AI-Academy/rizzo-flow` (730 stars) | 2026-09-21 | Yes |

The projects are real, not vaporware, and several ship genuine weights.

## Correction: these projects DO expose HTTP APIs

An earlier draft of this ADR wrongly implied the alternatives offered no API. That
was wrong, and it materially changed the picture. Verified from each project's own
README and source:

| Project | HTTP API | Endpoint | Jev-compatible | Serve command |
| --- | --- | --- | --- | --- |
| Kev | Yes | `POST /v1/systemone` on `:8009` | **Yes** — official TypeSafe SDK works unchanged | `uv run --extra serve python -m kev.serve --run jaredpalmer/kev-4b --port 8009` |
| Rizzo Flow | Yes | `POST /v1/systemone` on `:8017` | **Yes** — same body/response shape | `uv run rizzo serve` |
| NanoJev | Yes | `POST /api/evaluate` on `:8765` | No — own contract | `python scripts/serve_decisions.py --port 8765` |
| Laya (MLX) | No (library only) | — | No | `pip install laya-mlx`, in-process API |

Kev states it plainly: *"The API matches TypeSafe's System One, so you can point
their Python SDK at your local server."* Rizzo Flow adds: *"code written against the
TypeSafe API can point at `localhost` by changing one URL."* An independent
conformance suite (`jevcompat`) has been run against Rizzo's `/v1/systemone`,
reporting three precise differences.

This is significant for Gatewise specifically: `JevDecisionProvider` already accepts
a `base_url`, so pointing it at a local Kev or Rizzo server is a **configuration
change, not a code change** — the same mechanism used for the OpenRouter transport.

## Why they are still not the primary provider

**1. They would invalidate the central research question.** Gatewise exists to test
whether a fast *typed decision model* is a reliable decision layer. Substituting a
different model changes the subject of the experiment. The specification is explicit
that an alternative must be identified *as* an alternative and never passed off as
Jev.

**2. The hardware here cannot run the recommended checkpoints.** The development
machine has a GTX 1650 with 4 GB VRAM and 15.7 GB RAM. Kev's own table says Kev-4B
needs a 32 GB Mac, L40S, or H100, and that "Kev-0.8B runs on any Apple Silicon Mac,
L4" — the GTX 1650 is below that bar. Only the 0.8B checkpoint is plausible, on CPU,
which is slow enough to defeat the low-latency premise. Rizzo Flow is friendlier: it
runs on llama.cpp across CUDA, Vulkan, ROCm, SYCL, or plain CPU, and its authors
report CPU-only and Intel Iris Xe results. Its 1.7B Q8 build (~1.8 GB) would be the
realistic local option here, at a documented accuracy cost.

**3. Calibration is the entire value, and the evidence is mixed.** Jev's value is
*calibrated* confidence, so thresholds can be set rationally. Rizzo Flow states
plainly: *"Probabilities are uncalibrated unless you calibrate them on your own data,
and we make no claim of matching Jev or SemIf in quality."* Its response schema
encodes this as `probability_status` values including
`uncalibrated_conditional_option_scores` and
`temperature_scaled_requires_held_out_validation`. On its own benchmark Rizzo Flow
4B scores 0.648 accuracy / 0.205 Brier against Jev's 0.727 / 0.148 — respectable, but
measurably behind. Kev is the stronger claim: it reports per-checkpoint temperatures
fitted on held-out data, and Kev-27B at 0.848 accuracy / 0.236 Brier is close to
Jev's 0.857 / 0.211, though its own authors note *"Jev has only been run on the
development sets"* and that this is *"not a controlled comparison."* Either way, a
decision layer built on uncalibrated probabilities would produce confidently wrong
escalation thresholds — the most dangerous possible failure for this application.

**4. The popularity signals are not trustworthy.** Repositories created within the
last 12 days carry 4.5k-7.6k stars, and one Hugging Face model shows 4,246 likes
with 0 downloads. Star counts are not evidence of quality, and these particular
counts do not reflect organic adoption.

**5. Maturity risk.** All seven are days old, described by their own author as
evolving rapidly, with examples not independently tested.

## What was decided instead

1. **Jev via OpenRouter remains the primary provider.** It is the same real model,
   already integrated and verified up to billing, and costs $0.042 per million input
   tokens — pennies per pull request, not a meaningful budget item. The financial
   motivation to abandon it is negligible.
2. **The blocker is credits, not architecture.** Adding credits resolves the single
   remaining obstacle, after which the first real decisions can be observed.
3. **Kev is recorded as the preferred baseline for the evaluation harness**, per the
   specification's requirement to compare providers. It is the strongest candidate
   because it publishes weights, reports per-checkpoint calibration, and claims the
   TypeSafe System One API shape. It is explicitly a **baseline for measurement, not a
   production fallback**.
4. **A local provider can be enabled with configuration only.** Because Kev and Rizzo
   Flow both serve `/v1/systemone`, running one locally requires setting
   `TYPESAFE_BASE_URL` to the local server and supplying any non-empty API key. No new
   provider class is required. This is a *deliberate escape hatch for an unfunded
   account*, and it must be labelled as a different model wherever its output is
   recorded — the provider name is `jev` because the wire format matches, so the
   transport and model identifiers must be persisted separately to avoid
   misattributing local results to hosted Jev.

## Revisit trigger

Revisit if a project publishes independently reproduced calibration data on decision
tasks, or if Gatewise's decision quality proves inadequate at a volume where Jev's
cost becomes material. Neither condition is met today.

## Consequences

- No additional provider is implemented now, avoiding untested code on the critical
  path.
- The provider abstraction is now justified by a concrete, named candidate rather than
  speculation.
- If credits never become available, the honest outcome is to report the blocked
  milestone — not to quietly substitute a weaker model and present its output as
  Jev's.
