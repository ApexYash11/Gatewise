"""Static contract tests for the ``action.yml`` GitHub Action.

The Action is configuration, not Python: these tests parse the file and pin
its security-relevant shape — composite steps in order, no floating action
refs, the PR number taken only from the pull-request event, secrets only via
inputs, and the fail-loud ordering (comment posted before the review's exit
code is re-raised).
"""

from __future__ import annotations

import re
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
    """Immutable pins: a full commit SHA with the release tag kept as a comment.

    A tag can be repointed at code the token never approved; the SHA cannot.
    """
    refs = [step["uses"] for step in steps if "uses" in step]
    assert refs, "the action must reference setup-python and github-script"
    for ref in refs:
        _action, _, version = ref.partition("@")
        assert re.fullmatch(r"[0-9a-f]{40}", version), (
            f"{ref} must pin the full commit SHA, not a mutable tag"
        )


def test_pr_number_comes_only_from_the_event(action: dict, steps: list[dict]) -> None:
    """An undefined shell variable here would run the review against nothing.

    Every composite `run` block reads values through the step environment, so
    a crafted caller input cannot break out of the script text.
    """
    text = ACTION_PATH.read_text(encoding="utf-8")
    assert "${{ github.event.number }}" in text
    assert "$PR" not in text
    for step in steps:
        if "run" in step:
            for var in ("${{ inputs.", "${{ github.event.", "${{ github.repository }}"):
                assert var not in step["run"], f"{step.get('name')} interpolates {var}"


def test_comment_step_updates_one_marked_comment(steps: list[dict]) -> None:
    """One triage comment per PR, owned by the token's own account.

    The author predicate is the authenticated login, not the account type: a
    caller-supplied user token posts `User` comments that a Bot-only check
    would miss, and another bot's marked comment must never be claimed.
    """
    comment = step_by_name(steps, "Post the triage comment")
    assert "steps.review.outcome" in comment.get("if", ""), (
        "the comment must wait for the review step, not run on validation-only"
    )
    script = comment["with"]["script"]
    assert MARKER in script
    assert "updateComment" in script and "createComment" in script
    assert "getAuthenticated" in script
    assert "comment.user.login" in script and "me.data.login" in script


def test_failed_reviews_comment_first_then_fail(steps: list[dict]) -> None:
    """The review's exit code is captured and re-raised after the comment.

    stderr joins the report file, so a fetch/config failure still lands on
    the PR as text; an empty report can never replace the triage comment
    with a bare marker.
    """
    review = step_by_name(steps, "Review the pull request")
    assert "exit-code=$?" in review["run"]
    assert review["id"] == "review"
    assert "2>&1" in review["run"]
    assert "no report output" in review["run"]
    failing = step_by_name(steps, "Fail the run when the review failed")
    assert failing.get("if") == "always()"
    assert "steps.review.outputs.exit-code" in failing["run"]


def test_secrets_flow_only_through_inputs(action: dict) -> None:
    """No default verdict without a key, and no key baked into the file.

    The review step's credential environment must read the declared inputs
    only: callers cannot smuggle a constant past the inputs surface.
    """
    keyed = {
        name
        for name, spec in action["inputs"].items()
        if "api-key" in name
    }
    assert {"typesafe-api-key", "jev-api-key", "openrouter-api-key"} <= keyed
    text = ACTION_PATH.read_text(encoding="utf-8")
    assert "sk-" not in text
    steps = action["runs"]["steps"]
    validate = step_by_name(steps, "Validate inputs")
    assert "exit 1" in validate["run"]
    env = step_by_name(steps, "Review the pull request")["env"]
    assert "inputs.typesafe-api-key" in env["TYPESAFE_API_KEY"]
    assert "inputs.jev-api-key" in env["TYPESAFE_API_KEY"]
    assert "inputs.openrouter-api-key" in env["OPENROUTER_API_KEY"]
    assert "steps.review.outputs.exit-code" in (
        step_by_name(steps, "Fail the run when the review failed")["run"]
    )


def test_permissions_documented_for_consumers(action: dict) -> None:
    """Least privilege from the distribution invariants, restated for users."""
    text = ACTION_PATH.read_text(encoding="utf-8")
    for permission in ("pull-requests: write", "issues: write", "contents: read"):
        assert permission in text
