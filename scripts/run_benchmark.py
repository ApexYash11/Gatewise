"""Run a decision provider over a labelled dataset and print a report.

    python scripts/run_benchmark.py
    python scripts/run_benchmark.py --dataset benchmarks/pr_triage_seed.json

The report prints the dataset's provenance next to its metrics, because a
benchmark result without knowing who produced the labels is not evidence. It also
prints the failure count beside the accuracy, so a provider cannot appear strong
by declining the hard cases.

This is measurement, not marketing. A dataset of assistant-assessed labels is
labelled as such in the output and must not be reported as human-validated
accuracy.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "packages")

from dotenv import load_dotenv

load_dotenv()

from config import Settings  # noqa: E402
from decisions.jev import JevDecisionProvider  # noqa: E402
from decisions.registry import load_registry  # noqa: E402
from evaluation import compare, load_dataset, run_dataset  # noqa: E402

DEFAULT_DATASET = "benchmarks/pr_triage_seed.json"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument(
        "--limit", type=int, default=0, help="Evaluate only the first N cases."
    )
    args = parser.parse_args()

    path = Path(args.dataset)
    if not path.exists():
        print(f"BLOCKED: dataset not found at {path}")
        return 2

    dataset = load_dataset(path)
    if args.limit:
        dataset.cases = dataset.cases[: args.limit]

    metadata = dataset.metadata()
    print(f"dataset       : {metadata['name']}@v{metadata['version']}")
    print(f"cases         : {metadata['case_count']}")
    print(f"label sources : {metadata['label_sources']}")
    if not metadata["human_validated"]:
        print("provenance    : NOT human-validated; smoke-test only")
    print()

    try:
        settings = Settings()
        api_key, base_url = settings.jev_credentials()
    except RuntimeError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    provider = JevDecisionProvider(
        api_key,
        settings.jev_model,
        base_url=base_url,
        transport_name=settings.jev_transport,
    )
    print(f"provider      : {provider.name} / {provider.model} via {provider.transport}")
    print(f"official jev  : {provider.is_official_jev}\n")
    print("running...")

    try:
        report = await run_dataset(provider, dataset, load_registry())
    finally:
        await provider.close()

    summary = report.summary()
    print()
    print(json.dumps(summary, indent=2))

    if report.failures:
        print(f"\n{len(report.failures)} case(s) failed:")
        for failure in report.failures:
            print(f"  {failure['case']}: {failure['error']}")

    print("\ncomparison rows")
    for row in compare([report]):
        print(
            f"  {row['provider']:>6} | {row['dataset']:>18} | "
            f"security_f1={row['security_review_f1']} "
            f"risk_acc={row['pr_risk_accuracy']} "
            f"p50={row['latency_p50_ms']}ms cost=${row['cost_usd']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
