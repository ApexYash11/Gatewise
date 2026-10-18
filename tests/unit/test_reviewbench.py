"""Tests for the source-native ReviewBench adapter."""

from __future__ import annotations

import json

import pytest

from gatewise.evaluation import ReviewBenchError, load_reviewbench


def write_reviewbench(tmp_path, *, findings, head="abcdef0123456789"):
    root = tmp_path / "ReviewBench"
    (root / "corpus").mkdir(parents=True)
    (root / "golden").mkdir()
    entry = {
        "nwo": "octo/repo",
        "pr_number": 17,
        "pr_url": "https://github.com/octo/repo/pull/17",
        "head": head,
    }
    (root / "corpus" / "manifest.json").write_text(json.dumps([entry]), encoding="utf-8")
    golden = {
        "pr": {"repo": "https://github.com/octo/repo", "pr_number": 17, "head": head},
        "findings": findings,
    }
    (root / "golden" / f"octo_repo_17-{head[:8]}.json").write_text(
        json.dumps(golden), encoding="utf-8"
    )
    return root


def finding(**overrides):
    value = {
        "category": "security",
        "severity": "high",
        "tp_fp": "tp",
        "producer": "human_review",
        "source": {"type": "review_comment", "author": "maintainer"},
    }
    value.update(overrides)
    return value


def test_reviewbench_summary_preserves_native_provenance(tmp_path):
    root = write_reviewbench(
        tmp_path,
        findings=[
            finding(),
            finding(tp_fp="fp", producer="llm_review", source={"type": "llm_review"}),
        ],
    )

    summary = load_reviewbench(root, source_revision="a" * 40).summary()

    assert summary["case_count"] == 1
    assert summary["finding_count"] == 2
    assert summary["disposition"] == {"fp": 1, "tp": 1}
    assert summary["category"] == {"security": 2}
    assert summary["severity"] == {"high": 2}
    assert summary["producer"] == {"human_review": 1, "llm_review": 1}
    assert summary["source_type"] == {"llm_review": 1, "review_comment": 1}
    assert summary["gatewise_triage_accuracy"] is None
    assert "not labels" in summary["caveat"]


def test_reviewbench_requires_a_revision_and_matching_golden_identity(tmp_path):
    root = write_reviewbench(tmp_path, findings=[finding()])

    with pytest.raises(ReviewBenchError, match="source_revision"):
        load_reviewbench(root, source_revision="")

    golden = root / "golden" / "octo_repo_17-abcdef01.json"
    payload = json.loads(golden.read_text(encoding="utf-8"))
    payload["pr"]["head"] = "wrong"
    golden.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReviewBenchError, match="identity"):
        load_reviewbench(root, source_revision="a" * 40)


def test_reviewbench_rejects_unknown_disposition(tmp_path):
    root = write_reviewbench(tmp_path, findings=[finding(tp_fp="maybe")])

    with pytest.raises(ReviewBenchError, match="disposition"):
        load_reviewbench(root, source_revision="a" * 40)


@pytest.mark.parametrize("field", ["category", "severity", "producer"])
def test_reviewbench_rejects_non_string_native_labels(tmp_path, field):
    malformed = finding()
    malformed[field] = None
    root = write_reviewbench(tmp_path, findings=[malformed])

    with pytest.raises(ReviewBenchError, match="labels must be strings"):
        load_reviewbench(root, source_revision="a" * 40)
