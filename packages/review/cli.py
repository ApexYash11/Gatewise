"""The ``gatewise`` command-line interface.

    gatewise review owner/name 123
    gatewise review owner/name#123
    gatewise review owner/name 123 --no-execute

Exit codes, stable because automation depends on them:

    0  reviewed (and actions performed when a token was available)
    2  usage error: no pull request number could be read
    3  the decision model failed; the run is recorded, nothing was executed
    4  the pull request could not be fetched from GitHub
    5  the decision provider is not configured
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from config import Settings
from github.events import WebhookParseError
from github.fetch import PullRequestFetchError

from .loop import run_review
from .render import render_review

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DECISION_FAILED = 3
EXIT_FETCH_FAILED = 4
EXIT_NOT_CONFIGURED = 5


def parse_reference(repository: str, number: int | None) -> tuple[str, int] | None:
    """Resolve ``('owner/name', 123)`` from the CLI's two argument styles.

    Accepts ``owner/name 123`` or ``owner/name#123``. Returns None when no
    number can be read; the caller decides what that means (usage error).
    """
    if number is not None:
        return repository, number
    repo, _, tail = repository.partition("#")
    if repo and tail.isdigit():
        return repo, int(tail)
    return None


async def _run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="gatewise",
        description=(
            "Decision layer for pull requests: classify a PR with a typed "
            "decision model, record the run, and perform only the actions it "
            "justifies."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    review = subcommands.add_parser(
        "review", help="Review one pull request end to end."
    )
    review.add_argument(
        "repository", metavar="OWNER/NAME", help="as 'owner/name' or 'owner/name#123'"
    )
    review.add_argument("number", nargs="?", type=int, metavar="NUMBER")
    review.add_argument(
        "--no-execute",
        action="store_true",
        help="plan and record actions, but never perform them against GitHub",
    )
    args = parser.parse_args(argv)

    parsed = parse_reference(args.repository, args.number)
    if parsed is None:
        print(
            f"error: no pull request number in {args.repository!r}. "
            "Use 'owner/name 123' or 'owner/name#123'.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    repository, number = parsed

    settings: Any = Settings()
    try:
        settings.jev_credentials()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_NOT_CONFIGURED

    if args.no_execute:
        token = None
    else:
        token = settings.github_token

    try:
        result = await run_review(repository, number, token=token, settings=settings)
    except (PullRequestFetchError, WebhookParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FETCH_FAILED

    if args.no_execute and result.actions:
        body = render_review(result, execution_note="plan-only run: --no-execute")
    elif not result.action_results and not settings.github_token:
        body = render_review(result, execution_note="no GitHub token was set")
    else:
        body = render_review(result)
    print(body)

    if not result.run.succeeded:
        return EXIT_DECISION_FAILED
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``gatewise`` console script."""
    return asyncio.run(_run(list(argv) if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
