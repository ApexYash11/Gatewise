"""Tests for on-demand pull request fetching.

The GitHub API is stubbed at the HTTP boundary, so these run offline. What is
under test is the *translation*: a fetched pull request must reach the decision
layer as the same event the webhook parser would have produced.
"""

from __future__ import annotations

import json

import httpx
import pytest

from github import (
    MAX_FILES,
    PullRequestFetchError,
    build_webhook_payload,
    fetch_pull_request,
    validate_repository,
)

PR = {
    "number": 12,
    "title": "Add a rate limiter",
    "body": "Caps requests per token.",
    "user": {"login": "dev"},
    "base": {"ref": "main", "repo": {"full_name": "octo/repo"}},
    "head": {"ref": "feat/limit", "sha": "cafebabe"},
    "labels": [{"name": "feature"}],
    "draft": False,
}

FILES = [
    {"filename": "app.py", "additions": 5, "deletions": 1, "patch": "+x = 1"},
    {"filename": "tests/test_app.py", "additions": 9, "deletions": 0},
]


def stub_client(pulls=None, files=None, status=200, seen=None):
    """An httpx client that answers the two endpoints the fetcher calls."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url.path))
        if seen is not None:
            seen.append(request.headers.get("Authorization"))
        if request.url.path.endswith("/files"):
            return httpx.Response(status, json=FILES if files is None else files)
        return httpx.Response(status, json=PR if pulls is None else pulls)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.github.com",
    )
    return client, calls


@pytest.mark.parametrize(
    "value",
    ["octo/repo", "ApexYash11/Gatewise", "a/b", "octo/repo.with.dots", " octo/repo "],
)
def test_valid_repositories_are_accepted(value):
    assert "/" in validate_repository(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "octo",
        "octo/",
        "/repo",
        "octo/repo/../../etc",
        "oct o/repo",
        "http://evil.test/x",
        "octo/repo?x=1",
        "octo/repo#frag",
        "octo//repo",
        "a" * 200 + "/b",
        "octo/repo\nX-Injected: 1",
    ],
)
def test_malformed_repositories_are_rejected(value):
    """The repository is interpolated into a URL, so this is a trust boundary.

    Path traversal, a full URL, a query string, and header injection all have to
    fail here rather than being handed to the HTTP client.
    """
    with pytest.raises(PullRequestFetchError):
        validate_repository(value)


async def test_fetch_produces_a_normalized_event():
    client, calls = stub_client()
    async with client:
        event = await fetch_pull_request("octo/repo", 12, client=client)

    assert event.repository == "octo/repo"
    assert event.number == 12
    assert event.title == "Add a rate limiter"
    assert event.author == "dev"
    assert event.base_branch == "main"
    assert event.head_branch == "feat/limit"
    assert event.head_sha == "cafebabe"
    assert event.labels == ("feature",)
    assert not event.draft
    # The files endpoint is what supplies the names a webhook payload lacks.
    assert event.changed_files == ("app.py", "tests/test_app.py")
    assert calls == ["/repos/octo/repo/pulls/12", "/repos/octo/repo/pulls/12/files"]


async def test_fetch_rejects_a_non_positive_number():
    client, _ = stub_client()
    async with client:
        for bad in (0, -3):
            with pytest.raises(PullRequestFetchError):
                await fetch_pull_request("octo/repo", bad, client=client)
        # A bool is an int subclass, so True would otherwise pass as pull request 1.
        with pytest.raises(PullRequestFetchError):
            await fetch_pull_request("octo/repo", True, client=client)


async def test_fetch_reports_a_missing_pull_request_clearly():
    client, _ = stub_client(status=404)
    async with client:
        with pytest.raises(PullRequestFetchError) as excinfo:
            await fetch_pull_request("octo/repo", 12, client=client)

    assert "no such pull request" in str(excinfo.value).lower()


async def test_fetch_sends_the_token_when_one_is_given():
    seen: list[str | None] = []
    client, _ = stub_client(seen=seen)
    async with client:
        await fetch_pull_request("octo/repo", 12, token="secret", client=client)

    assert seen and all(value == "Bearer secret" for value in seen)


async def test_fetch_omits_authorization_without_a_token():
    """Public repositories are fetched unauthenticated, so no empty bearer header
    is sent; GitHub rejects a malformed Authorization header outright."""
    seen: list[str | None] = []
    client, _ = stub_client(seen=seen)
    async with client:
        await fetch_pull_request("octo/repo", 12, client=client)

    assert all(value is None for value in seen)


def test_payload_carries_changed_file_names():
    """The parser reads ``changed_files_list``; without it a reviewed pull request
    looks identical to one that touches no files at all."""
    payload = build_webhook_payload(PR, FILES)

    assert b"changed_files_list" in payload
    assert b"app.py" in payload
    # The patch is untrusted text and is bounded rather than sent whole.
    assert b"+x = 1" in payload


def test_payload_bounds_the_file_list():
    many = [{"filename": f"f{i}.py"} for i in range(MAX_FILES + 50)]
    decoded = json.loads(build_webhook_payload(PR, many))

    assert len(decoded["pull_request"]["changed_files_list"]) == MAX_FILES


def test_payload_tolerates_a_missing_files_list():
    """GitHub returns a list, but a malformed response must not raise here."""
    decoded = json.loads(build_webhook_payload(PR, None))  # type: ignore[arg-type]

    assert decoded["pull_request"]["changed_files_list"] == []


async def test_fetch_does_not_retry_a_404():
    """A missing pull request will still be missing on the next attempt, so
    retrying only delays the error the user has to wait for."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, json={"message": "Not Found"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as client:
        with pytest.raises(PullRequestFetchError):
            await fetch_pull_request("octo/repo", 12, client=client)

    assert attempts == 1

