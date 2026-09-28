"""Tests for the versioned question registry."""

from __future__ import annotations

import pytest
import yaml

from decisions.provider import DecisionValidationError
from decisions.registry import QuestionRegistry, load_registry
from decisions.schemas import ChoiceQuestion, NoulQuestion, ScoreQuestion

MVP_QUESTIONS = [
    "pr_category",
    "pr_risk",
    "pr_breaking_change",
    "pr_additional_testing",
    "pr_maintainer_review",
    "pr_security_review",
]


def test_shipped_registry_defines_all_six_mvp_questions():
    registry = load_registry()
    assert sorted(q.name for q in registry) == sorted(MVP_QUESTIONS)


def test_questions_are_versioned():
    registry = load_registry()
    for question in registry:
        assert question.version == 1
        assert question.identifier == f"{question.name}@1"
    assert set(registry.identifiers()) == {f"{n}@1" for n in MVP_QUESTIONS}


def test_mvp_question_types_match_the_specification():
    registry = load_registry()
    assert isinstance(registry.get("pr_category").question, ChoiceQuestion)
    assert isinstance(registry.get("pr_risk").question, ScoreQuestion)
    for name in (
        "pr_breaking_change",
        "pr_additional_testing",
        "pr_maintainer_review",
        "pr_security_review",
    ):
        assert isinstance(registry.get(name).question, NoulQuestion)


def test_category_criteria_match_the_specified_option_set():
    registry = load_registry()
    criteria = registry.get("pr_category").question.criteria
    assert set(criteria) == {
        "bug",
        "feature",
        "refactor",
        "documentation",
        "test",
        "dependency",
        "security",
        "infrastructure",
        "other",
    }


def test_risk_rubric_is_ordered_from_trivial_to_critical():
    registry = load_registry()
    criteria = registry.get("pr_risk").question.criteria
    assert len(criteria) == 5
    assert criteria[0].lower().startswith("trivial")
    assert criteria[-1].lower().startswith("critical")


def test_noul_criteria_keys_are_normalized_to_strings():
    """YAML parses bare true:/false: as booleans; the API needs 'true'/'false'."""
    registry = load_registry()
    criteria = registry.get("pr_security_review").question.criteria
    assert set(criteria) == {"true", "false"}


def test_build_request_batches_every_question_into_one_payload():
    registry = load_registry()
    request = registry.build_request()
    assert set(request) == set(MVP_QUESTIONS)
    assert all(q.instructions for q in request.values()), "every question needs instructions"


def test_latest_returns_highest_version(tmp_path):
    path = tmp_path / "q.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "questions": [
                    {
                        "name": "q",
                        "version": 1,
                        "type": "noul",
                        "instructions": "v1",
                        "criteria": {"true": "yes", "false": "no"},
                    },
                    {
                        "name": "q",
                        "version": 2,
                        "type": "noul",
                        "instructions": "v2",
                        "criteria": {"true": "yes", "false": "no"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    registry = load_registry(path)
    assert registry.latest("q").version == 2
    assert registry.get("q", 1).question.instructions == "v1"
    assert len(registry) == 2


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"name": "q", "type": "noul"}, "version"),
        ({"name": "q", "version": 1, "type": "vibes"}, "unsupported type"),
        ({"name": "q", "version": 1, "type": "choice"}, "criteria"),
        ({"name": "q", "version": 1, "type": "score", "criteria": ["only one"]}, "levels"),
    ],
)
def test_malformed_questions_fail_at_load_time(tmp_path, entry, message):
    """A broken rubric must fail on load, never mid-decision."""
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump({"questions": [entry]}), encoding="utf-8")
    with pytest.raises((DecisionValidationError, ValueError)) as excinfo:
        load_registry(path)
    assert message in str(excinfo.value)


def test_duplicate_questions_are_rejected(tmp_path):
    path = tmp_path / "dup.yaml"
    entry = {
        "name": "q",
        "version": 1,
        "type": "noul",
        "instructions": "x",
        "criteria": {"true": "y", "false": "n"},
    }
    path.write_text(yaml.safe_dump({"questions": [entry, dict(entry)]}), encoding="utf-8")
    with pytest.raises(DecisionValidationError, match="duplicate"):
        load_registry(path)


def test_unknown_question_name_raises():
    registry = load_registry()
    with pytest.raises(DecisionValidationError, match="no question named"):
        registry.latest("does_not_exist")
