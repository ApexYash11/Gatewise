"""Fetch maintainer-labelled public pull requests into a Gatewise dataset.

The labels come from the repository's own maintainer-applied GitHub labels,
mapped onto one Gatewise question (``pr_category`` by default). They are real
human judgements, but they were made for another purpose and were not annotated
against Gatewise's rubric, so the output is marked ``label_source: "derived"``.
It must never be reported as human-validated Gatewise accuracy.

    python scripts/fetch_github_label_dataset.py \
        --repository python/cpython \
        --label type-bug=bug \
        --label type-feature=feature \
        --label docs=documentation \
        --per-label 3 \
        --output benchmarks/pr_triage_cpython_labels.json

The fetcher uses GitHub's search API and then reads each pull request's changed
files. A token is optional for public repositories but raises the rate limit. It
is read from ``GITHUB_TOKEN`` or ``GH_TOKEN`` and is never written to the output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"

#: GitHub owner and repository names. Checked before any request is made.
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")

#: Keep one huge PR body from dominating the dataset file. The context builder
#: applies its own, larger cap before anything reaches the model.
MAX_BODY_CHARS = 4_000

#: A backport repeats the same change on another release branch. Counting both
#: the original and its backports would double-weight one piece of work.
_BACKPORT_PREFIX = re.compile(r"^\s*\[\d+(?:\.\d+)?\]\s*")
_TRAILING_GH = re.compile(r"\s*\(GH-\d+\)\s*$")


def parse_mapping(raw: str) -> tuple[str, str]:
    """Parse ``GITHUB_LABEL=GATEWISE_VALUE`` from the command line."""
    label, separator, value = raw.partition("=")
    if not separator or not label.strip() or not value.strip():
        raise argparse.ArgumentTypeError("expected GITHUB_LABEL=GATEWISE_VALUE")
    return label.strip(), value.strip()


def _get_json(
    client: httpx.Client, path: str, *, params: dict[str, Any] | None = None
) -> Any:
    """GET JSON with a failure message that names the request, not the token."""
    try:
        response = client.get(path, params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200].replace("\n", " ")
        raise RuntimeError(
            f"GitHub returned {exc.response.status_code} for {path}: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"could not reach GitHub for {path}: {exc}") from exc
    return response.json()


def search_pull_requests(
    client: httpx.Client, repository: str, label: str, limit: int
) -> list[dict[str, Any]]:
    """Return merged pull requests carrying ``label``, newest first."""
    query = f'repo:{repository} is:pr is:merged label:"{label}"'
    payload = _get_json(
        client,
        "/search/issues",
        params={"q": query, "per_page": limit, "sort": "updated", "order": "desc"},
    )
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("GitHub search response has no items list")
    return [
        item
        for item in items
        if isinstance(item, dict) and item.get("number") and item.get("pull_request")
    ]


def _is_backport(title: str) -> bool:
    """Whether a PR is a release-branch backport of an earlier change."""
    return bool(_BACKPORT_PREFIX.match(title))


def _normalize_title(title: str) -> str:
    """Collapse an original PR and its release-branch backports to one identity."""
    normalized = _BACKPORT_PREFIX.sub("", title)
    normalized = _TRAILING_GH.sub("", normalized)
    return " ".join(normalized.split()).lower()


def pull_request_files(
    client: httpx.Client, repository: str, number: int, max_files: int
) -> tuple[str, ...]:
    """Return the changed file names for one pull request."""
    payload = _get_json(
        client,
        f"/repos/{repository}/pulls/{number}/files",
        params={"per_page": max_files},
    )
    if not isinstance(payload, list):
        return ()
    return tuple(
        str(entry["filename"])
        for entry in payload
        if isinstance(entry, dict) and entry.get("filename")
    )


def build_case(
    repository: str,
    item: dict[str, Any],
    changed_files: tuple[str, ...],
    *,
    github_label: str,
    question: str,
    gatewise_value: str,
) -> dict[str, Any]:
    """Build one dataset case with explicit borrowed-label provenance."""
    number = int(item["number"])
    url = str(item.get("html_url") or f"https://github.com/{repository}/pull/{number}")
    notes = (
        f"Maintainer-applied GitHub label {github_label!r} mapped to "
        f"{question}={gatewise_value!r}; not annotated against the Gatewise rubric. "
        f"Source: {url}"
    )
    return {
        "id": f"{repository.replace('/', '-')}-{number}",
        "repository": repository,
        "number": number,
        "title": str(item.get("title") or ""),
        "description": (str(item.get("body") or "")[:MAX_BODY_CHARS] or None),
        "author": str((item.get("user") or {}).get("login") or "unknown"),
        "changed_files": list(changed_files),
        "labels": {question: gatewise_value},
        "label_source": "derived",
        "notes": notes,
    }


def fetch_dataset(
    repository: str,
    mappings: list[tuple[str, str]],
    *,
    question: str,
    per_label: int,
    max_files: int,
    token: str | None,
    include_backports: bool,
) -> dict[str, Any]:
    """Fetch one case per merged PR for each label mapping."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    candidates_per_label = min(100, max(per_label * 10, 20))
    cases: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    seen_titles: set[str] = set()
    per_value: dict[str, int] = {}
    skipped = 0
    with httpx.Client(base_url=GITHUB_API, headers=headers, timeout=20.0) as client:
        for github_label, gatewise_value in mappings:
            if per_value.get(gatewise_value, 0) >= per_label:
                continue
            items = search_pull_requests(
                client, repository, github_label, candidates_per_label
            )
            for item in items:
                if per_value.get(gatewise_value, 0) >= per_label:
                    break
                number = int(item["number"])
                raw_title = str(item.get("title") or "")
                if not include_backports and _is_backport(raw_title):
                    skipped += 1
                    continue
                title = _normalize_title(raw_title)
                if number in seen_numbers or title in seen_titles:
                    skipped += 1
                    continue
                seen_numbers.add(number)
                seen_titles.add(title)
                files = pull_request_files(client, repository, number, max_files)
                cases.append(
                    build_case(
                        repository,
                        item,
                        files,
                        github_label=github_label,
                        question=question,
                        gatewise_value=gatewise_value,
                    )
                )
                per_value[gatewise_value] = per_value.get(gatewise_value, 0) + 1

    if not cases:
        raise RuntimeError("no merged pull requests matched the supplied labels")

    return {
        "name": f"pr-triage-{repository.replace('/', '-')}-labels",
        "version": 1,
        "description": (
            "Derived from maintainer-applied GitHub labels, not independently "
            "annotated against Gatewise's rubrics. Use for basic harness "
            "measurement only; never cite as human-validated accuracy."
        ),
        "provenance": {
            "source_repository": repository,
            "retrieval_method": "GitHub search + pull request files API",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "label_mapping": {label: value for label, value in mappings},
            "question": question,
            "label_source": "derived",
            "caveat": (
                "Repository labels are human-applied but were not produced for "
                "the Gatewise question rubric."
            ),
        },
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="GitHub repository as owner/name")
    parser.add_argument(
        "--label",
        action="append",
        required=True,
        type=parse_mapping,
        metavar="GITHUB_LABEL=GATEWISE_VALUE",
        help="Label mapping; repeat for each category. Earlier mappings win ties.",
    )
    parser.add_argument(
        "--question",
        default="pr_category",
        help="Gatewise question to label (default: pr_category).",
    )
    parser.add_argument(
        "--per-label",
        type=int,
        default=3,
        help="Unique cases to take per Gatewise value (default: 3).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=100,
        help="Maximum changed files recorded per case (default: 100; GitHub caps a page at 100).",
    )
    parser.add_argument(
        "--output",
        default="benchmarks/pr_triage_github_labels.json",
        help="Output dataset path.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub token; defaults to GITHUB_TOKEN or GH_TOKEN.",
    )
    parser.add_argument(
        "--include-backports",
        action="store_true",
        help="Include release-branch backports (skipped by default to avoid duplicates).",
    )
    args = parser.parse_args(argv)

    if not _REPOSITORY.match(args.repository):
        parser.error("--repository must be owner/name")
    if not 1 <= args.per_label <= 100:
        parser.error("--per-label must be between 1 and 100")
    if not 1 <= args.max_files <= 100:
        parser.error("--max-files must be between 1 and 100")

    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    try:
        dataset = fetch_dataset(
            args.repository,
            args.label,
            question=args.question,
            per_label=args.per_label,
            max_files=args.max_files,
            token=token,
            include_backports=args.include_backports,
        )
    except RuntimeError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset, indent=2) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    for case in dataset["cases"]:
        value = str(case["labels"][args.question])
        counts[value] = counts.get(value, 0) + 1

    print(f"wrote {len(dataset['cases'])} cases to {output}")
    print(f"question : {args.question}")
    print(f"labels   : {dict(sorted(counts.items()))}")
    print("provenance: derived from maintainer-applied GitHub labels")
    print("caveat    : not independently annotated for Gatewise; not human-validated accuracy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
