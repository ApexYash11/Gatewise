"""Tests for the ``gatewise`` CLI argument handling and exit codes."""

from __future__ import annotations

import pytest

from gatewise.actions.pipeline import EvaluationRun
from gatewise.context import PullRequestContext
from gatewise.github.events import PullRequestEvent
from gatewise.review.cli import (
    EXIT_ACTION_FAILED,
    EXIT_DECISION_FAILED,
    EXIT_USAGE,
    exit_code,
    main,
    parse_reference,
)
from gatewise.review.loop import ReviewResult


def test_parse_reference_takes_repository_and_number():
    assert parse_reference("octo/repo", 12) == ("octo/repo", 12)


def test_parse_reference_takes_a_hash_form():
    assert parse_reference("octo/repo#12", None) == ("octo/repo", 12)


def test_parse_reference_rejects_a_repository_alone():
    assert parse_reference("octo/repo", None) is None


def test_parse_reference_rejects_a_non_numeric_hash():
    assert parse_reference("octo/repo#latest", None) is None


def test_parse_reference_rejects_zero():
    """Zero is a usage mistake, not a fetch failure."""
    assert parse_reference("octo/repo", 0) is None
    assert parse_reference("octo/repo#0", None) is None


def test_parse_reference_rejects_negatives():
    assert parse_reference("octo/repo", -3) is None


def make_result(*, succeeded: bool, statuses: tuple[str, ...] = ()) -> ReviewResult:
    """A minimal result for exit-code mapping tests; no network is touched."""
    run = EvaluationRun(
        repository="octo/repo",
        pull_request_number=1,
        provider="jev",
        model="jev-latest",
        is_official_jev=True,
        question_versions=[],
    )
    run.status = run.status.SUCCEEDED if succeeded else run.status.FAILED
    from gatewise.actions.executor import ActionResult

    return ReviewResult(
        event=PullRequestEvent(
            delivery_id=None,
            action="opened",
            repository="octo/repo",
            number=1,
            title="",
            description=None,
            author="",
            base_branch="",
            head_branch="",
            labels=(),
            changed_files=(),
            draft=False,
            head_sha="",
            raw={},
        ),
        run=run,
        context=PullRequestContext(state={}),
        action_results=[
            ActionResult("add_label", status, "risk:high") for status in statuses
        ],
    )


def test_exit_code_reports_evaluation_failure():
    assert (
        exit_code(make_result(succeeded=False))
        == EXIT_DECISION_FAILED
    )


def test_exit_code_ok_for_success():
    assert exit_code(make_result(succeeded=True)) == 0


def test_exit_code_reports_a_rejected_action():
    """A GitHub write that failed must not look like success to automation."""
    assert exit_code(make_result(succeeded=True, statuses=("performed", "failed"))) == (
        EXIT_ACTION_FAILED
    )


def test_exit_code_tolerates_a_skipped_action():
    """Skipped (request-review sentinel) is designed behaviour, not failure."""
    assert exit_code(make_result(succeeded=True, statuses=("skipped",))) == 0


def test_usage_error_when_no_number_is_readable():
    argv = ["review", "octo/repo"]
    assert main(argv) == EXIT_USAGE


def test_unknown_command_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["status"])
    assert excinfo.value.code == EXIT_USAGE


def test_no_command_exits_cleanly():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == EXIT_USAGE


def test_hash_form_with_garbage_is_usage():
    assert main(["review", "octo/repo#nope"]) == EXIT_USAGE


def test_zero_number_is_usage_not_fetch():
    """Exit 2 without touching the network."""
    assert main(["review", "octo/repo", "0"]) == EXIT_USAGE
