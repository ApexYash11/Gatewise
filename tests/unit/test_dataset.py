"""Tests for dataset loading and provenance."""

from __future__ import annotations

import json

import pytest

from evaluation import DatasetError, load_dataset


def write(tmp_path, payload):
    path = tmp_path / "d.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def case(**overrides):
    base = {
        "id": "c1",
        "repository": "octo/repo",
        "number": 1,
        "title": "Bump the parser",
        "description": "Raises a limit.",
        "labels": {"pr_category": "dependency", "pr_risk": 2},
    }
    base.update(overrides)
    return base


def test_loads_a_valid_dataset(tmp_path):
    path = write(
        tmp_path,
        {"name": "demo", "version": 2, "cases": [case(), case(id="c2")]},
    )
    dataset = load_dataset(path)

    assert dataset.name == "demo"
    assert dataset.version == 2
    assert len(dataset) == 2
    assert dataset.cases[0].id == "c1"


def test_dataset_reports_label_provenance(tmp_path):
    """Provenance must be visible, or self-assessed labels read as human truth."""
    path = write(
        tmp_path,
        {
            "name": "mixed",
            "cases": [case(id="a", label_source="human"), case(id="b", label_source="assistant")],
        },
    )
    metadata = load_dataset(path).metadata()

    assert metadata["label_sources"] == {"human": 1, "assistant": 1}
    assert metadata["human_validated"] is False, "mixed labels are not human-validated"


def test_fully_human_dataset_is_marked_validated(tmp_path):
    path = write(tmp_path, {"name": "d", "cases": [case(label_source="human")]})
    assert load_dataset(path).metadata()["human_validated"] is True


def test_case_builds_the_same_context_shape_as_the_pipeline(tmp_path):
    path = write(tmp_path, {"name": "d", "cases": [case(changed_files=["a.py", "b.py"])]})
    context = load_dataset(path).cases[0].to_context()

    assert context["pull_request"]["files_changed_count"] == 2
    assert context["pull_request"]["changed_files"] == ["a.py", "b.py"]
    assert context["untrusted_content"]["title"] == "Bump the parser"
    assert "description" in context["untrusted_content"]


def test_unlabelled_case_is_rejected(tmp_path):
    """An unlabelled case would silently shrink the denominator."""
    path = write(tmp_path, {"name": "d", "cases": [case(id="x", labels={})]})
    with pytest.raises(DatasetError, match="no labels"):
        load_dataset(path)


def test_duplicate_ids_are_rejected(tmp_path):
    path = write(tmp_path, {"name": "d", "cases": [case(), case()]})
    with pytest.raises(DatasetError, match="duplicate"):
        load_dataset(path)


def test_missing_required_field_is_rejected(tmp_path):
    broken = case()
    del broken["title"]
    path = write(tmp_path, {"name": "d", "cases": [broken]})
    with pytest.raises(DatasetError, match="missing"):
        load_dataset(path)


def test_unknown_label_source_is_rejected(tmp_path):
    path = write(tmp_path, {"name": "d", "cases": [case(label_source="vibes")]})
    with pytest.raises(DatasetError, match="label_source"):
        load_dataset(path)


def test_empty_or_missing_cases_rejected(tmp_path):
    with pytest.raises(DatasetError):
        load_dataset(write(tmp_path, {"name": "d", "cases": []}))
    with pytest.raises(DatasetError):
        load_dataset(write(tmp_path, {"name": "d"}))


def test_invalid_json_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(DatasetError, match="not valid JSON"):
        load_dataset(path)


def test_missing_file_is_reported_clearly(tmp_path):
    with pytest.raises(DatasetError, match="not found"):
        load_dataset(tmp_path / "nope.json")
