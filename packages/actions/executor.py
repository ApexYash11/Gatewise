"""Execute planned actions against the GitHub API.

This is the only module that talks to GitHub with write access, and it is
deliberately small and explicit about what it may do.

What it will do:
  - ``add_label``
  - ``comment``
  - ``request_review``
  - ``trigger_workflow``

What it will never do:
  - ``merge``, ``delete``, ``force_push``, ``release``, ``deployment``

The excluded set is enforced by :data:`ALLOWED_ACTIONS` rather than by call-site
discipline, so adding a destructive action requires editing one allowlist rather
than trusting that no future caller reaches for it. The specification calls for
those actions to stay out until explicit safeguards exist.

Two safety properties hold here:

- **Least privilege.** The token needs only Issues, Pull requests, and Actions
  write. Nothing in this module reads or writes repository contents.
- **A failed action is recorded, not retried silently.** The caller marks the
  action failed; it is never reported as done.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

#: The only action types this module will ever perform.
ALLOWED_ACTIONS = frozenset(
    {"add_label", "comment", "request_review", "trigger_workflow"}
)

#: Never performed, regardless of what a plan asks for.
FORBIDDEN_ACTIONS = frozenset(
    {"merge", "delete", "force_push", "release", "deployment"}
)

GITHUB_API = "https://api.github.com"


class ActionError(Exception):
    """An action could not be performed."""


class ActionNotPermitted(ActionError):
    """The requested action type is not in the allowlist."""


@dataclass(frozen=True)
class ActionResult:
    """Outcome of one attempted action."""

    action_type: str
    status: str  # "performed" | "skipped" | "failed"
    detail: str = ""
    http_status: int | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "performed"


class GitHubActionExecutor:
    """Performs planned actions over the GitHub REST API.

    Args:
        token: A fine-grained token with Issues, Pull requests, and Actions write
            on the target repository. Never logged or echoed.
        client: Injected HTTP client, so tests can stub the network without
            contacting GitHub.
    """

    def __init__(self, token: str, client: httpx.AsyncClient | None = None) -> None:
        if not token:
            raise ValueError(
                "a GitHub token is required; Gatewise does not execute actions "
                "unauthenticated"
            )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=GITHUB_API,
            timeout=15.0,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def perform(
        self, action: dict[str, Any], *, repository: str, number: int
    ) -> ActionResult:
        """Perform one planned action.

        Returns a result rather than raising for an API failure, so one rejected
        action does not abort the rest of a plan. An unknown or forbidden action
        type is refused outright.
        """
        action_type = action.get("action_type", "")
        if action_type in FORBIDDEN_ACTIONS:
            return ActionResult(
                action_type,
                "skipped",
                f"{action_type} is not permitted by Gatewise",
            )
        if action_type not in ALLOWED_ACTIONS:
            return ActionResult(
                action_type, "skipped", f"unsupported action type {action_type!r}"
            )

        try:
            if action_type == "add_label":
                return await self._add_label(repository, number, action["target"])
            if action_type == "comment":
                return await self._comment(repository, number, action["target"])
            if action_type == "request_review":
                return await self._request_review(repository, number, action["target"])
            return await self._trigger_workflow(repository, action["target"])
        except httpx.HTTPStatusError as exc:
            return ActionResult(
                action_type,
                "failed",
                f"GitHub returned {exc.response.status_code}",
                exc.response.status_code,
            )
        except (httpx.HTTPError, KeyError) as exc:
            return ActionResult(action_type, "failed", str(exc))

    async def _add_label(
        self, repository: str, number: int, label: str
    ) -> ActionResult:
        """Label a pull request.

        This uses the *issues* labels endpoint, not a pull request one: GitHub
        models a pull request as an issue internally, so the Issues write
        permission is what governs this call. Requesting Pull requests write
        alone produces a 403 here.
        """
        response = await self._client.post(
            f"/repos/{repository}/issues/{number}/labels",
            json={"labels": [label]},
        )
        response.raise_for_status()
        return ActionResult(
            "add_label", "performed", label, response.status_code
        )

    async def _comment(
        self, repository: str, number: int, body: str
    ) -> ActionResult:
        response = await self._client.post(
            f"/repos/{repository}/issues/{number}/comments", json={"body": body}
        )
        response.raise_for_status()
        return ActionResult("comment", "performed", body[:60], response.status_code)

    async def _request_review(
        self, repository: str, number: int, reviewer: str
    ) -> ActionResult:
        """Ask a specific user for review.

        The planner currently emits a sentinel target rather than a username,
        because choosing *who* should review is a policy question the model is not
        asked. It is skipped rather than guessed, so Gatewise never invents a
        reviewer.
        """
        if not reviewer or reviewer in {"request-review", "unassigned"}:
            return ActionResult(
                "request_review",
                "skipped",
                "no reviewer named; Gatewise does not guess who should review",
            )
        response = await self._client.post(
            f"/repos/{repository}/pulls/{number}/requested_reviewers",
            json={"reviewers": [reviewer]},
        )
        response.raise_for_status()
        return ActionResult(
            "request_review", "performed", reviewer, response.status_code
        )

    async def _trigger_workflow(
        self, repository: str, workflow_file: str
    ) -> ActionResult:
        """Dispatch a workflow via workflow_dispatch.

        A workflow can only be dispatched if it declares a ``workflow_dispatch``
        trigger; otherwise GitHub returns 422. The failure is reported rather than
        retried with a different method.
        """
        response = await self._client.post(
            f"/repos/{repository}/actions/workflows/{workflow_file}/dispatches",
            json={"ref": "main"},
        )
        response.raise_for_status()
        return ActionResult(
            "trigger_workflow", "performed", workflow_file, response.status_code
        )