"""Tests for GitHub action execution.

The HTTP client is stubbed, so these never contact GitHub. The property that
matters most is negative: a forbidden action must be refused before any request is
made.
"""

from __future__ import annotations

import httpx
import pytest

from actions import (
    ALLOWED_ACTIONS,
    FORBIDDEN_ACTIONS,
    GitHubActionExecutor,
)


def make_executor(handler):
    """An executor whose HTTP layer is a test double."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    )
    return GitHubActionExecutor("test-token", client=client)


async def test_add_label_calls_the_issues_endpoint(real_jev_payload):
    """PRs are issues in GitHub's model, so labels go to /issues/{n}/labels."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"name": "risk:high"}])

    executor = make_executor(handler)
    result = await executor.perform(
        {"action_type": "add_label", "target": "risk:high"},
        repository="octo/repo",
        number=42,
    )

    assert result.succeeded
    assert result.action_type == "add_label"
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/repos/octo/repo/issues/42/labels"


@pytest.mark.parametrize("action_type", sorted(FORBIDDEN_ACTIONS))
async def test_forbidden_actions_are_refused_without_any_request(action_type):
    """merge, delete, force_push, release and deployment must never execute."""
    called = False

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    executor = make_executor(handler)
    result = await executor.perform(
        {"action_type": action_type, "target": "main"},
        repository="octo/repo",
        number=42,
    )

    assert result.status == "skipped"
    assert "not permitted" in result.detail
    assert called is False, "no HTTP request may be made for a forbidden action"


async def test_unknown_action_type_is_refused():
    executor = make_executor(lambda r: httpx.Response(200, json={}))
    result = await executor.perform(
        {"action_type": "something_new", "target": "x"},
        repository="octo/repo",
        number=1,
    )
    assert result.status == "skipped"
    assert "unsupported" in result.detail


async def test_allowlist_covers_exactly_the_intended_actions():
    assert ALLOWED_ACTIONS == {
        "add_label",
        "comment",
        "request_review",
        "trigger_workflow",
    }
    assert not (ALLOWED_ACTIONS & FORBIDDEN_ACTIONS)


async def test_request_review_is_skipped_when_no_reviewer_is_named():
    """Gatewise must not invent who should review a pull request."""
    called = False

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal called
        called = True
        return httpx.Response(201, json={})

    executor = make_executor(handler)
    result = await executor.perform(
        {"action_type": "request_review", "target": "request-review"},
        repository="octo/repo",
        number=42,
    )

    assert result.status == "skipped"
    assert "does not guess" in result.detail
    assert called is False


async def test_request_review_with_a_named_reviewer_is_performed():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={})

    executor = make_executor(handler)
    result = await executor.perform(
        {"action_type": "request_review", "target": "octocat"},
        repository="octo/repo",
        number=42,
    )

    assert result.succeeded
    assert seen[0].url.path == "/repos/octo/repo/pulls/42/requested_reviewers"


async def test_api_error_is_reported_as_failed_not_raised():
    """One rejected action must not abort the rest of a plan."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Resource not accessible"})

    executor = make_executor(handler)
    result = await executor.perform(
        {"action_type": "add_label", "target": "risk:high"},
        repository="octo/repo",
        number=42,
    )

    assert result.status == "failed"
    assert result.http_status == 403
    assert "403" in result.detail


async def test_comment_posts_an_issue_comment():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={})

    executor = make_executor(handler)
    result = await executor.perform(
        {"action_type": "comment", "target": "Gatewise: risk 3 of 5"},
        repository="octo/repo",
        number=42,
    )

    assert result.succeeded
    assert seen[0].url.path == "/repos/octo/repo/issues/42/comments"


async def test_executor_requires_a_token():
    with pytest.raises(ValueError, match="token is required"):
        GitHubActionExecutor("")
