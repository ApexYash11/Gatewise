"""Load and summarize ReviewBench's native, human-reviewed finding corpus.

This adapter deliberately does not turn ReviewBench findings into Gatewise's six
triage answers. ReviewBench labels individual review findings (including their
category, severity, producer, and true/false-positive disposition), while
Gatewise evaluates pull-request triage decisions. Keeping those measurements
separate prevents source-native evidence from becoming a false accuracy claim.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REVIEWBENCH_REPOSITORY = "https://github.com/review-bench/ReviewBench"


class ReviewBenchError(Exception):
    """The local ReviewBench checkout does not match the supported source shape."""


@dataclass(frozen=True)
class ReviewBenchFinding:
    """One source-native finding from ReviewBench's reviewed golden set."""

    category: str
    severity: str
    disposition: str
    producer: str
    source_type: str


@dataclass(frozen=True)
class ReviewBenchCase:
    """A pull request and the reviewed findings associated with its selected head."""

    repository: str
    number: int
    url: str
    head: str
    findings: tuple[ReviewBenchFinding, ...]


@dataclass(frozen=True)
class ReviewBenchDataset:
    """A locally checked-out, revision-pinned ReviewBench corpus."""

    source_revision: str
    cases: tuple[ReviewBenchCase, ...]
    source_repository: str = REVIEWBENCH_REPOSITORY

    def summary(self) -> dict[str, Any]:
        """Return native ReviewBench counts without asserting Gatewise quality."""
        findings = [finding for case in self.cases for finding in case.findings]
        return {
            "source": "ReviewBench",
            "source_repository": self.source_repository,
            "source_revision": self.source_revision,
            "case_count": len(self.cases),
            "finding_count": len(findings),
            "disposition": dict(sorted(Counter(f.disposition for f in findings).items())),
            "category": dict(sorted(Counter(f.category for f in findings).items())),
            "severity": dict(sorted(Counter(f.severity for f in findings).items())),
            "producer": dict(sorted(Counter(f.producer for f in findings).items())),
            "source_type": dict(sorted(Counter(f.source_type for f in findings).items())),
            "gatewise_triage_accuracy": None,
            "caveat": (
                "ReviewBench findings are source-native review evidence, not labels for "
                "Gatewise's six pull-request triage questions."
            ),
        }


def load_reviewbench(
    root: str | Path,
    *,
    source_revision: str,
    limit: int | None = None,
) -> ReviewBenchDataset:
    """Load ReviewBench's manifest and corresponding golden files from ``root``.

    ``source_revision`` is required because a mutable checkout is not sufficient
    provenance for a benchmark report. It should be the checked-out ReviewBench
    commit SHA. The caller owns retrieval; this loader is deliberately offline.
    """
    if not source_revision.strip():
        raise ReviewBenchError("source_revision must identify the checked-out ReviewBench commit")
    if limit is not None and limit < 1:
        raise ReviewBenchError("limit must be positive when provided")

    directory = Path(root)
    manifest = _read_json(directory / "corpus" / "manifest.json")
    if not isinstance(manifest, list) or not manifest:
        raise ReviewBenchError("manifest.json: expected a non-empty list")

    selected = manifest[:limit] if limit else manifest
    cases = tuple(_load_case(directory, entry) for entry in selected)
    return ReviewBenchDataset(source_revision=source_revision, cases=cases)


def _load_case(root: Path, entry: Any) -> ReviewBenchCase:
    if not isinstance(entry, dict):
        raise ReviewBenchError("manifest.json: every entry must be an object")
    required = ("nwo", "pr_number", "pr_url", "head")
    missing = [field for field in required if field not in entry]
    if missing:
        raise ReviewBenchError(f"manifest.json: case missing {', '.join(missing)}")

    repository = str(entry["nwo"])
    number = int(entry["pr_number"])
    head = str(entry["head"])
    golden_name = f"{repository.replace('/', '_')}_{number}-{head[:8]}.json"
    golden = _read_json(root / "golden" / golden_name)
    if not isinstance(golden, dict):
        raise ReviewBenchError(f"{golden_name}: expected an object")
    _validate_pr(golden.get("pr"), repository, number, head, golden_name)

    raw_findings = golden.get("findings")
    if not isinstance(raw_findings, list):
        raise ReviewBenchError(f"{golden_name}: expected a findings list")
    findings = tuple(_parse_finding(finding, golden_name) for finding in raw_findings)
    return ReviewBenchCase(
        repository=repository,
        number=number,
        url=str(entry["pr_url"]),
        head=head,
        findings=findings,
    )


def _validate_pr(
    raw: Any, repository: str, number: int, head: str, filename: str
) -> None:
    if not isinstance(raw, dict):
        raise ReviewBenchError(f"{filename}: expected a pr object")
    expected_repository = f"https://github.com/{repository}"
    if (
        raw.get("repo") != expected_repository
        or raw.get("pr_number") != number
        or raw.get("head") != head
    ):
        raise ReviewBenchError(f"{filename}: golden PR identity does not match manifest")


def _parse_finding(raw: Any, filename: str) -> ReviewBenchFinding:
    if not isinstance(raw, dict):
        raise ReviewBenchError(f"{filename}: every finding must be an object")
    required = ("category", "severity", "tp_fp", "producer", "source")
    missing = [field for field in required if field not in raw]
    if missing:
        raise ReviewBenchError(f"{filename}: finding missing {', '.join(missing)}")
    source = raw["source"]
    if not isinstance(source, dict) or not isinstance(source.get("type"), str):
        raise ReviewBenchError(f"{filename}: finding source needs a type")
    disposition = str(raw["tp_fp"])
    if disposition not in {"tp", "fp"}:
        raise ReviewBenchError(f"{filename}: unsupported finding disposition {disposition!r}")
    return ReviewBenchFinding(
        category=str(raw["category"]),
        severity=str(raw["severity"]),
        disposition=disposition,
        producer=str(raw["producer"]),
        source_type=source["type"],
    )


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise ReviewBenchError(f"ReviewBench source file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReviewBenchError(f"{path.name} is not valid JSON: {exc}") from exc
