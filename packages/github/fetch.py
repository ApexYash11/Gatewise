"""Fetch a real pull request and render it as a webhook payload.

The webhook endpoint is the product's real ingestion path, and a manual review has
to travel the same road. Rather than calling the pipeline directly, this module
fetches the pull request and renders it into the *exact* body GitHub would send,
so signature verification, parsing, context building, evaluation, and recording
all run through their production code paths. A shortcut here would mean the
dashboard could record a verdict the real webhook path could never produce.

Two details are easy to get wrong:

- **Changed files are not in the webhook payload.** GitHub sends a file *count*,
  not a list, so :func:`packages.github.events.parse_pull_request_event` reads
  ``changed_files_list``, which this module populates from the files endpoint.
  Without that step every pull request looks like it touches no files and the
  file-category questions are asked against an empty list.
- **A missing token is not an error for public repositories.** Fetching is
  unauthenticated by default; a token only raises the rate limit and is needed for
  private repositories.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from .events import PullRequestEvent, parse_pull_request_event

GITHUB_API = "https://api.github.com"

#: GitHub owner and repository names. Enforced before any request is made, so a
#: malformed or hostile value cannot reach the network or the URL path.
_NAME = r"[A-Za-z0-9_.-]{1,100}"
REPOSITORY_PATTERN = re.compile(rf"^{_NAME}/{_NAME}$")

#: GitHub's own caps. Asking for more is silently truncated, so the limit is
#: applied here and the truncation stays visible in the recorded context.
MAX_FILES = 300

#: A diff is not sent to the model. File *paths* carry the signal, and bodies are
#: untrusted attacker-controlled text, so a bounded prefix is all that is read.
MAX_PATCH_CHARS = 400


class PullRequestFetchError(Exception):
    """A pull request could not be fetched."""


def validate_repository(repository: str) -> str:
    """Return the repository if it is a plausible ``owner/name``, else raise.

    This is the boundary that stops the review endpoint from becoming a request
    proxy: the value is interpolated into a URL, so it is constrained to the
    characters GitHub itself permits in those two segments.
    """
    candidate = (repository or "").strip().strip("/")
    if not REPOSITORY_PATTERN.match(candidate):
        raise PullRequestFetchError(
            f"{repository!r} is not a valid repository; expected 'owner/name'"
        )
    return candidate


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    attempts: int = 3,
) -> Any:
    """GET JSON, retrying transient connection failures.

    A flaky network must not be reported as "this pull request has no decisions",
    so transport errors are retried and only a real HTTP status is surfaced.
    """
    request_headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        **(headers or {}),
    }
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(url, headers=request_headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code == 404:
                raise PullRequestFetchError(
                    "no such pull request, or it is in a private repository"
                ) from exc
            if code in (403, 429):
                raise PullRequestFetchError(
                    "GitHub refused the request; this is usually an unauthenticated "
                    "rate limit, so set GITHUB_TOKEN and retry"
                ) from exc
            raise PullRequestFetchError(f"GitHub returned {code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            if attempt == attempts:
                break
            await asyncio.sleep(2 * attempt)
    raise PullRequestFetchError(f"could not reach GitHub: {last}")


def build_webhook_payload(pr: dict[str, Any], files: list[Any]) -> bytes:
    """Render a fetched pull request as the body GitHub would have sent.

    ``changed_files_list`` is added deliberately: it is what the parser reads to
    recover file names, which the real payload does not carry.
    """
    # GitHub returns a list, but a malformed or truncated response must degrade to
    # "no files" rather than raise: a review with no file list is still worth
    # running, and the alternative is a 500 on the reader's only way in.
    if not isinstance(files, list):
        files = []
    changed = [
        {
            "filename": entry.get("filename"),
            "status": entry.get("status"),
            "additions": entry.get("additions"),
            "deletions": entry.get("deletions"),
            "changes": entry.get("changes"),
            "patch": (entry.get("patch") or "")[:MAX_PATCH_CHARS],
        }
        for entry in files[:MAX_FILES]
        if isinstance(entry, dict) and entry.get("filename")
    ]
    return json.dumps(
        {
            "action": "opened",
            "repository": {"full_name": pr["base"]["repo"]["full_name"]},
            "pull_request": {
                "number": pr["number"],
                "title": pr["title"],
                "body": pr.get("body"),
                "user": {"login": pr["user"]["login"]},
                "base": {"ref": pr["base"]["ref"]},
                "head": {"ref": pr["head"]["ref"], "sha": pr["head"]["sha"]},
                "labels": [
                    {"name": label["name"]}
                    for label in pr.get("labels", [])
                    if isinstance(label, dict) and label.get("name")
                ],
                "draft": pr.get("draft", False),
                "changed_files": len(changed),
                "changed_files_list": changed,
            },
        }
    ).encode("utf-8")


async def fetch_pull_request(
    repository: str,
    number: int,
    *,
    token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> PullRequestEvent:
    """Fetch a pull request and return it as a normalized event.

    The result is a genuine :class:`PullRequestEvent`, identical in shape to one
    produced by the webhook parser, so nothing downstream needs to know whether the
    event arrived over HTTP or was fetched on demand.
    """
    repository = validate_repository(repository)
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise PullRequestFetchError(
            "pull request number must be a positive integer"
        )

    owns_client = client is None
    http = client or httpx.AsyncClient(
        base_url=GITHUB_API, timeout=20.0, follow_redirects=False
    )
    # Set per request rather than in the client's default headers. Building the
    # header into a client we construct works, but an *injected* client would then
    # silently drop the token and fall back to an unauthenticated request, which
    # still succeeds for a public repository and only fails later on a private one.
    auth = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        pr = await _get_json(
            http, f"/repos/{repository}/pulls/{number}", headers=auth
        )
        files = await _get_json(
            http, f"/repos/{repository}/pulls/{number}/files", headers=auth
        )
    finally:
        if owns_client:
            await http.aclose()

    if not isinstance(files, list):
        files = []

    parsed = parse_pull_request_event(
        build_webhook_payload(pr, files), event="pull_request"
    )
    return PullRequestEvent(
        delivery_id=None,
        action=parsed.action,
        repository=parsed.repository,
        number=parsed.number,
        title=parsed.title,
        description=parsed.description,
        author=parsed.author,
        base_branch=parsed.base_branch,
        head_branch=parsed.head_branch,
        labels=parsed.labels,
        changed_files=tuple(
            str(entry["filename"])
            for entry in files[:MAX_FILES]
            if isinstance(entry, dict) and entry.get("filename")
        ),
        draft=parsed.draft,
        head_sha=parsed.head_sha,
        raw=parsed.raw,
    )
