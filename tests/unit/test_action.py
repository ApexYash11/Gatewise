"""Static contract tests for the ``action.yml`` GitHub Action.

The Action is configuration, not Python: these tests parse the file and pin
its security-relevant shape — composite steps in order, no floating action
refs, the PR number taken only from the pull-request event, secrets only via
inputs, and the fail-loud ordering (comment posted before the review's exit
code is re-raised).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ACTION_PATH = Path(__file__).resolve().parents[2] / "action.yml"
MARKER = "<!-- gatewise-triage -->"


@pytest.fixture(scope="module")
def action() -> dict:
    return yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def steps(action: dict) -> list[dict]:
    return action["runs"]["steps"]


def step_by_name(steps: list[dict], name: str) -> dict:
    return next(step for step in steps if step.get("name") == name)


def test_action_is_composite_with_the_expected_steps(steps: list[dict]) -> None:
    names = [step.get("name") for step in steps]
    assert names == [
        "Validate inputs",
        "Set up Python",
        "Install Gatewise",
        "Review the pull request",
        "Post the triage comment",
        "Fail the run when the review failed",
    ]


def test_referenced_actions_are_pinned(steps: list[dict]) -> None:
    """Floating majors (`@v5`) let a future release change what the token sees."""
    refs = [step["uses"] for step in steps if "uses" in step]
    assert refs, "the action must reference setup-python and github-script"
    for ref in refs:
        _action, _, version = ref.partition("@")
        assert version and version != "main" and version[0] == "v"
        assert len(version.split(".")) >= 2, f"{ref} must pin a release, not a major"


def test_pr_number_comes_only_from_the_event(action: dict, steps: list[dict]) -> None:
    """An undefined shell variable here would run the review against nothing."""
    text = ACTION_PATH.read_text(encoding="utf-8")
    assert "${{ github.event.number }}" in text
    review = step_by_name(steps, "Review the pull request")
    assert "${{ github.event.number }}" in review["run"]
    assert "$PR" not in text


def test_comment_step_updates_one_marked_comment(steps: list[dict]) -> None:
    """One triage comment per PR: find the marker, update it, else create it."""
    comment = step_by_name(steps, "Post the triage comment")
    assert comment.get("if") == "always()"
    script = comment["with"]["script"]
    assert MARKER in script
    assert "updateComment" in script and "createComment" in script
    assert "Bot" in script, "only the bot's own comment may be updated"


def test_failed_reviews_comment_first_then_fail(steps: list[dict]) -> None:
    """The review's exit code is captured and re-raised after the comment."""
    review = step_by_name(steps, "Review the pull request")
    assert "exit-code=$?" in review["run"]
    assert review["id"] == "review"
    failing = step_by_name(steps, "Fail the run when the review failed")
    assert failing.get("if") == "always()"
    assert "steps.review.outputs.exit-code" in failing["run"]


def test_secrets_flow_only_through_inputs(action: dict) -> None:
    """No default verdict without a key, and no key baked into the file."""
    keyed = {
        name
        for name, spec in action["inputs"].items()
        if "api-key" in name
    }
    assert {"typesafe-api-key", "openrouter-api-key"} <= keyed
    text = ACTION_PATH.read_text(encoding="utf-8")
    assert "sk-" not in text
    validate = step_by_name(action["runs"]["steps"], "Validate inputs")
    assert "exit 1" in validate["run"]


def test_permissions_documented_for_consumers(action: dict) -> None:
    """Least privilege from the distribution invariants, restated for users."""
    text = ACTION_PATH.read_text(encoding="utf-8")
    for permission in ("pull-requests: write", "issues: write", "contents: read"):
        assert permission in text
