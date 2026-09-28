"""Build the smallest useful representation of a pull request for the model.

The full repository is never sent. The builder assembles a compact, structured
state object in which every attacker-influenced string lives under a single
``untrusted_content`` key, physically separated from the trusted ``pull_request``
metadata the builder itself computed (file counts, diff stats, branch names).

That separation is the point: the model can read the PR description, but the
description is never in a position where it could be read as an instruction. See
:mod:`context.untrusted` for the second, textual layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .untrusted import SanitizedText, sanitize_untrusted

#: Per-field caps, so one enormous file cannot crowd out the rest of the context.
MAX_TITLE_CHARS = 1_000
MAX_DESCRIPTION_CHARS = 20_000
MAX_DIFF_CHARS = 60_000
MAX_COMMIT_SUBJECTS = 20
MAX_FILES_LISTED = 500

#: Test-file heuristics used only to *label* files for the model. These are
#: descriptive hints, not decisions: nothing here sets a risk level or selects a
#: workflow. All judgement remains the model's.
_TEST_PATH_HINTS = ("test/", "tests/", "spec/", "__tests__/", "_test.", ".test.", ".spec.")
_CONFIG_PATH_HINTS = (
    "package.json",
    "requirements",
    "pyproject.toml",
    "cargo.toml",
    "go.mod",
    "dockerfile",
    ".github/workflows/",
    "terraform",
    "k8s",
    "helm",
)
_LOCKFILES = (
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "cargo.lock",
    "go.sum",
    "requirements.txt",
    "uv.lock",
)


@dataclass
class PullRequestContext:
    """A built, ready-to-send decision context plus its sanitization report."""

    state: dict[str, Any]
    flags: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_injection_attempts(self) -> bool:
        return any(self.flags.values())

    def flagged_fields(self) -> list[str]:
        return sorted(name for name, hits in self.flags.items() if hits)


def _classify_path(path: str) -> str:
    lowered = path.lower()
    if any(hint in lowered for hint in _LOCKFILES):
        return "lockfile"
    if any(hint in lowered for hint in _CONFIG_PATH_HINTS):
        return "configuration"
    if any(hint in lowered for hint in _TEST_PATH_HINTS):
        return "test"
    return "source"


def build_context(
    *,
    number: int,
    title: str,
    description: str | None,
    author: str,
    base_branch: str,
    head_branch: str,
    labels: Sequence[str] = (),
    changed_files: Sequence[str] = (),
    diff: str | None = None,
    commit_subjects: Sequence[str] = (),
    draft: bool = False,
) -> PullRequestContext:
    """Assemble the decision state for one pull request.

    Trusted structural facts (counts, derived labels) are computed here. Untrusted
    prose is sanitized and placed in its own section.
    """
    flags: dict[str, list[str]] = {}
    untrusted: dict[str, Any] = {}

    def add(field_name: str, raw: str | None, *, max_length: int) -> SanitizedText:
        result = sanitize_untrusted(raw, max_length=max_length)
        if result.flagged:
            flags[field_name] = list(result.patterns)
        return result

    title_sanitized = add("title", title, max_length=MAX_TITLE_CHARS)
    untrusted["title"] = title_sanitized.sanitized

    if description:
        untrusted["description"] = add(
            "description", description, max_length=MAX_DESCRIPTION_CHARS
        ).sanitized

    if commit_subjects:
        cleaned: list[str] = []
        for subject in commit_subjects[:MAX_COMMIT_SUBJECTS]:
            result = add("commit_subjects", subject, max_length=MAX_TITLE_CHARS)
            if result.flagged:
                flags.setdefault("commit_subjects", []).extend(result.patterns)
            cleaned.append(result.sanitized)
        untrusted["commit_subjects"] = cleaned

    if diff:
        untrusted["diff"] = add("diff", diff, max_length=MAX_DIFF_CHARS).sanitized

    files = list(changed_files)
    categorized: dict[str, int] = {}
    for path in files:
        kind = _classify_path(path)
        categorized[kind] = categorized.get(kind, 0) + 1

    state: dict[str, Any] = {
        "pull_request": {
            "number": number,
            "author": author,
            "base_branch": base_branch,
            "head_branch": head_branch,
            "labels": list(labels),
            "draft": draft,
            "files_changed_count": len(files),
            "changed_files": files[:MAX_FILES_LISTED],
            "file_categories": categorized,
            "diff_truncated": bool(diff) and len(diff or "") > MAX_DIFF_CHARS,
        },
        "untrusted_content": untrusted,
    }

    return PullRequestContext(state=state, flags=flags)
