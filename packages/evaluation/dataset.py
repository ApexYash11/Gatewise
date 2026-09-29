"""Benchmark dataset loading.

A dataset is a set of cases, each pairing an engineering context with the
judgements a human made about it. Two properties are enforced, because a
benchmark without them produces numbers that look like evidence but are not:

- **Provenance is mandatory.** Every case declares who labelled it and how. A
  dataset of self-assessed labels is still useful for smoke-testing, but it must
  not be reported as human-validated accuracy. The report carries the label source
  so the distinction cannot be lost.
- **A label must exist for every question being scored.** Silently skipping a
  case because one label is missing would quietly shrink the denominator and
  inflate every metric.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

#: How a case's judgements were produced. Recorded on every case.
LabelSource = Literal["human", "assistant", "unlabelled"]


class DatasetError(Exception):
    """The dataset is malformed and cannot be used for measurement."""


@dataclass(frozen=True)
class Case:
    """One labelled engineering change."""

    id: str
    repository: str
    number: int
    title: str
    description: str | None
    author: str
    changed_files: tuple[str, ...]
    #: Question name -> expected value. Nouls are 0.0/1.0, choice is a string,
    #: score is a level index.
    labels: dict[str, Any]
    label_source: LabelSource = "human"
    notes: str = ""

    def to_context(self) -> dict[str, Any]:
        """Build the same context shape the live pipeline sends to the provider."""
        return {
            "pull_request": {
                "number": self.number,
                "author": self.author,
                "base_branch": "main",
                "head_branch": "benchmark",
                "labels": [],
                "draft": False,
                "files_changed_count": len(self.changed_files),
                "changed_files": list(self.changed_files),
            },
            "untrusted_content": {
                "title": self.title,
                **({"description": self.description} if self.description else {}),
            },
        }


@dataclass
class Dataset:
    """A named, versioned collection of labelled cases."""

    name: str
    version: int
    cases: list[Case] = field(default_factory=list)
    description: str = ""

    def __len__(self) -> int:
        return len(self.cases)

    @property
    def label_sources(self) -> set[str]:
        return {case.label_source for case in self.cases}

    def metadata(self) -> dict[str, Any]:
        """Provenance summary. Carried into every report."""
        sources: dict[str, int] = {}
        for case in self.cases:
            sources[case.label_source] = sources.get(case.label_source, 0) + 1
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "case_count": len(self.cases),
            "label_sources": sources,
            "human_validated": sources.get("human", 0) == len(self.cases) and bool(self.cases),
        }


def load_dataset(path: str | Path) -> Dataset:
    """Load a dataset from JSON.

    Raises:
        DatasetError: On a malformed file, a duplicate case id, or a case with no
            labels. An unlabelled case cannot contribute to any metric, so
            accepting it would only invite a misleading denominator.
    """
    file = Path(path)
    if not file.exists():
        raise DatasetError(f"dataset not found: {file}")

    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetError(f"{file.name} is not valid JSON: {exc}") from exc

    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise DatasetError(f"{file.name}: expected a non-empty 'cases' list")

    cases: list[Case] = []
    seen: set[str] = set()
    for raw in raw_cases:
        case = _parse_case(raw, file.name)
        if case.id in seen:
            raise DatasetError(f"{file.name}: duplicate case id {case.id!r}")
        if not case.labels:
            raise DatasetError(
                f"{file.name}: case {case.id!r} has no labels and cannot be scored"
            )
        seen.add(case.id)
        cases.append(case)

    return Dataset(
        name=data.get("name", file.stem),
        version=int(data.get("version", 1)),
        cases=cases,
        description=data.get("description", ""),
    )


def _parse_case(raw: dict[str, Any], filename: str) -> Case:
    missing = [key for key in ("id", "title", "repository", "number") if key not in raw]
    if missing:
        raise DatasetError(
            f"{filename}: a case is missing {', '.join(missing)}"
        )
    source = raw.get("label_source", "human")
    if source not in ("human", "assistant", "unlabelled"):
        raise DatasetError(
            f"{filename}: case {raw['id']!r} has unknown label_source {source!r}"
        )
    return Case(
        id=str(raw["id"]),
        repository=str(raw["repository"]),
        number=int(raw["number"]),
        title=str(raw["title"]),
        description=raw.get("description"),
        author=str(raw.get("author", "unknown")),
        changed_files=tuple(str(f) for f in raw.get("changed_files", [])),
        labels=dict(raw.get("labels", {})),
        label_source=source,
        notes=str(raw.get("notes", "")),
    )
