"""Summarize a revision-pinned local ReviewBench checkout.

This prints native ReviewBench finding counts only. It does not call a Gatewise
provider and does not report accuracy for Gatewise's six triage decisions.

    python scripts/summarize_reviewbench.py --root ../ReviewBench \
        --source-revision <reviewbench-commit-sha>
"""

from __future__ import annotations

import argparse
import json

from gatewise.evaluation.reviewbench import ReviewBenchError, load_reviewbench


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Path to a local ReviewBench checkout")
    parser.add_argument(
        "--source-revision",
        required=True,
        help="Exact ReviewBench commit SHA checked out at --root",
    )
    parser.add_argument("--limit", type=int, help="Summarize only the first N manifest cases")
    args = parser.parse_args()

    try:
        dataset = load_reviewbench(
            args.root, source_revision=args.source_revision, limit=args.limit
        )
    except ReviewBenchError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    print(json.dumps(dataset.summary(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
