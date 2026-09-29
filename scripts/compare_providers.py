"""Compare decision providers over the same labelled dataset.

    python scripts/compare_providers.py
    python scripts/compare_providers.py --threshold 0.6

The evaluation docs describe adding a baseline and comparing providers, but there
was no way to do it from the command line. This closes that gap.

Two transports are supported, and both serve a real decision model:

    Jev (hosted)      TYPESAFE_API_KEY or OPENROUTER_API_KEY
    Jev (local)       TYPESAFE_BASE_URL=http://127.0.0.1:8009, e.g. Kev or Rizzo

Both are compared over the identical dataset and question set, so a difference in
the results is a difference in the models rather than in the harness. The
dataset's label provenance is printed before any numbers, because a comparison
without knowing who labelled the data is not evidence.
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


def build_providers(settings: Settings):
    """Every reachable decision model, each labelled with where it runs.

    The hosted provider is included when a key is present. A local server is
    included only when TYPESAFE_BASE_URL points somewhere that is not TypeSafe's
    own endpoint, so running this script does not silently compare a host against
    itself.
    """
    providers = []
    if settings.has_jev_key:
        api_key, base_url = settings.jev_credentials()
        providers.append(
            JevDecisionProvider(
                api_key,
                settings.jev_model,
                base_url=base_url,
                transport_name=settings.jev_transport,
            )
        )
    local = settings.jev_base_url
    if local and "api.typesafe.ai" not in local:
        providers.append(
            JevDecisionProvider(
                settings.require_jev_key() if settings.has_jev_key else "local",
                settings.jev_model,
                base_url=local,
                transport_name="local",
            )
        )
    return providers


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Probability at which a noul counts as yes (default 0.5).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    path = Path(args.dataset)
    if not path.exists():
        print(f"BLOCKED: dataset not found at {path}")
        return 2

    dataset = load_dataset(path)
    metadata = dataset.metadata()

    settings = Settings()
    providers = build_providers(settings)
    if not providers:
        print("BLOCKED: no decision provider configured.")
        print("  Set TYPESAFE_API_KEY or OPENROUTER_API_KEY, or point")
        print("  TYPESAFE_BASE_URL at a local Jev-compatible server.")
        return 2

    registry = load_registry()
    reports = []
    for provider in providers:
        try:
            reports.append(
                await run_dataset(
                    provider, dataset, registry, threshold=args.threshold
                )
            )
        finally:
            await provider.close()

    if args.json:
        print(json.dumps([r.summary() for r in reports], indent=2))
        return 0

    print(f"dataset       : {metadata['name']}@v{metadata['version']}")
    print(f"cases         : {metadata['case_count']}")
    print(f"label sources : {metadata['label_sources']}")
    if not metadata["human_validated"]:
        print("provenance    : NOT human-validated; smoke-test only")
    print(f"threshold     : {args.threshold}\n")

    rows = compare(reports)
    header = f"{'transport':<12} {'model':<12} {'evaluated':>9} {'failed':>7} {'sec f1':>8} {'p50 ms':>8} {'cost $':>10}"
    print(header)
    print("-" * len(header))
    for row in rows:
        f1 = row["security_review_f1"]
        print(
            f"{row['provider']:<12} {row['model'][:12]:<12} {row['evaluated']:>9} "
            f"{row['failed']:>7} {('-' if f1 is None else f1):>8} "
            f"{row['latency_p50_ms']:>8} {row['cost_usd']:>10.6f}"
        )

    if len(rows) == 1:
        print(
            "\nOnly one provider was reachable. Set TYPESAFE_BASE_URL to a local\n"
            "Jev-compatible server (Kev, Rizzo Flow) to compare two."
        )
    else:
        print(
            "\nBoth rows ran the same dataset, questions and threshold. Any\n"
            "difference is the model, not the harness."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
