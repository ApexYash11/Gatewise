"""Tests for the ``gatewise`` CLI argument handling and exit codes."""

from __future__ import annotations

import pytest
from review.cli import EXIT_USAGE, main, parse_reference


def test_parse_reference_takes_repository_and_number():
    assert parse_reference("octo/repo", 12) == ("octo/repo", 12)


def test_parse_reference_takes_a_hash_form():
    assert parse_reference("octo/repo#12", None) == ("octo/repo", 12)


def test_parse_reference_rejects_a_repository_alone():
    assert parse_reference("octo/repo", None) is None


def test_parse_reference_rejects_a_non_numeric_hash():
    assert parse_reference("octo/repo#latest", None) is None


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
