# Evaluation

The evaluation harness scores a decision provider against labelled pull requests
and reports accuracy, precision, recall, F1, false positive rate, false negative
rate, Brier score, latency, token usage, and cost.

Its purpose is measurement. No claim that one provider is better than another is
made without running both over the same dataset with the same questions.

## Running it

```bash
python scripts/run_benchmark.py
python scripts/run_benchmark.py --dataset benchmarks/pr_triage_seed.json --limit 5
```

## What the current dataset is, and is not

`benchmarks/pr_triage_seed.json` holds four real pull requests with
**assistant-assessed** labels. This is stated in three places on purpose: the
dataset description, each case's `label_source` field, and the report output.

It exists to smoke-test the harness and to show what a report looks like. **It is
not evidence about decision quality.** The specification calls for 30
human-labelled pull requests to start, 100 for a meaningful experiment, and 500+
for a strong benchmark. None of those exist yet.

The loader enforces the distinction rather than trusting convention: `metadata()`
reports `human_validated: false` unless every case is labelled `human`, and the
script prints `NOT human-validated; smoke-test only`.

## Scoring rules

| Question type | Scored as | Why |
| --- | --- | --- |
| `noul` | confusion counts + Brier score | Policy thresholds probabilities, so calibration matters as well as classification. |
| `choice` | accuracy | No useful false-positive notion for a single chosen option. |
| `score` | **level** agreement, not raw float | Jev is non-deterministic; identical input returned 2.06 and 2.09 on two runs. Comparing floats would measure noise. |

A case contributes only to questions it actually labels, so a partially labelled
case cannot inflate a denominator.

## Why accuracy alone is not enough

A provider that never escalates scores 95% accuracy on a dataset that is 95%
"no", while missing every risky change. That is why false positive and false
negative rates are reported beside accuracy: a false alarm causes alert fatigue,
and a missed review is a missed vulnerability. They are different failures and
the metrics must distinguish them.

Failure counts sit beside accuracy for the same reason — a provider cannot look
strong by declining the hard cases. When the provider is unreachable, the report
shows `evaluated: 0, failed: N` and no confusion counts at all, rather than zeros
that could be misread as a score.

## Comparing providers

The runner depends only on `DecisionProvider`, so the same harness scores Jev, a
local Jev-compatible server such as Kev or Rizzo Flow, or any future provider.
`compare()` lines reports up side by side, and every row carries the dataset name
and size so a comparison cannot be quoted without its scope.

To add a baseline, point a second provider at the same dataset:

```bash
# local Jev-compatible server
set TYPESAFE_BASE_URL=http://127.0.0.1:8009
python scripts/run_benchmark.py
```

## Status

Implemented and tested: dataset loading with enforced provenance, metrics, the
provider-agnostic runner, failure accounting, and the comparison helper.

Not yet done: a human-labelled dataset, automated harvesting of real pull request
labels, and a multi-provider comparison run.
