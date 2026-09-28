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

## Why they are not the primary provider

**1. They would invalidate the central research question.** Gatewise exists to test
whether a fast *typed decision model* is a reliable decision layer. Substituting a
different model changes the subject of the experiment. The specification is explicit
that an alternative must be identified *as* an alternative and never passed off as
Jev.

**2. The hardware here cannot run them meaningfully.** The development machine has a
GTX 1650 with 4 GB VRAM and 15.7 GB RAM. The smallest Kev checkpoint (0.8B) is
plausible on CPU; the 4B that the project itself recommends as a starting point is
not. "Free" here means slow local inference, which defeats the low-latency premise the
decision layer depends on.

**3. Calibration is unproven, and calibration is the entire point.** Jev's value is
*calibrated* confidence, so thresholds can be set rationally. Rizzo Flow's own
response schema enumerates `probability_status` values including
`uncalibrated_conditional_option_scores` and
`temperature_scaled_requires_held_out_validation` — the project itself states its
probabilities may not be calibrated. A decision layer built on uncalibrated
probabilities would produce confidently wrong escalation thresholds, which is the most
dangerous possible failure for this application.

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
   because it publishes weights *and* claims the TypeSafe System One API shape, so it
   can be compared on the same dataset with minimal glue. It is explicitly a
   **baseline for measurement, not a production fallback**.

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
