"""Evaluate a real pull request end to end: fetch, decide, record, label.

    set GITHUB_TOKEN=... TYPESAFE_API_KEY=...
    python scripts/review_pr.py ApexYash11/Gatewise 1

This is the full loop in one command:

    fetch the real PR -> build context -> ask the real Jev model
    -> record the run -> apply the actions it justified

Fetch is unauthenticated when the repository is public, so only the labelling
step needs a token. The token is read from the environment and never written to a
file or echoed.
"""

import asyncio
import json
import os
import sys
import urllib.request

sys.path.insert(0, "packages")

from dotenv import load_dotenv

load_dotenv()

from actions import DecisionPipeline, GitHubActionExecutor  # noqa: E402
from audit import AuditStore, create_engine, create_schema, session_scope  # noqa: E402
from config import Settings  # noqa: E402
from context import build_context  # noqa: E402
from decisions.jev import JevDecisionProvider  # noqa: E402
from decisions.registry import load_registry  # noqa: E402
from decisions.schemas import ChoiceAnswer, ScoreAnswer  # noqa: E402
from github import compute_signature, parse_pull_request_event, verify_signature  # noqa: E402
from github.events import PullRequestEvent  # noqa: E402

DB_URL = os.environ.get("DATABASE_URL") or "sqlite+aiosqlite:///./gatewise.db"
USER_AGENT = "gatewise"


def fetch_json(url: str, token: str | None = None, attempts: int = 6):
    """GET a GitHub URL, retrying transient DNS and connection failures.

    Retries matter here: a failed fetch must not be confused with a pull request
    that has no decisions, and a flaky network must not abort a review mid-flight.
    """
    import time

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError:
            raise  # A real HTTP status, including 404, will not improve on retry.
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            if attempt == attempts:
                break
            time.sleep(2 * attempt)
    raise RuntimeError(f"could not reach {url} after {attempts} attempts: {last}")


def build_webhook_payload(pr: dict) -> bytes:
    """Render a fetched PR as the webhook body Gatewise already knows how to parse.

    Going through the real event parser and signature check means this exercises
    the same code path a real delivery does, rather than a shortcut.
    """
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
                "labels": [{"name": label["name"]} for label in pr.get("labels", [])],
                "draft": pr.get("draft", False),
            },
        }
    ).encode("utf-8")

async def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    repository, number = sys.argv[1], int(sys.argv[2])
    token = os.environ.get("GITHUB_TOKEN")
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET") or "local-review-secret"

    pr = fetch_json(f"https://api.github.com/repos/{repository}/pulls/{number}", token)
    print(f"pull request : {repository}#{number}  {pr['title']}")

    files = fetch_json(
        f"https://api.github.com/repos/{repository}/pulls/{number}/files", token
    )
    print(f"changed files: {len(files)}")

    # Route through signature verification and the real event parser.
    body = build_webhook_payload(pr)
    verify_signature(body, compute_signature(body, secret), secret)
    parsed = parse_pull_request_event(body, event="pull_request")
    event = PullRequestEvent(
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
        changed_files=tuple(f["filename"] for f in files),
        draft=parsed.draft,
        head_sha=parsed.head_sha,
        raw=parsed.raw,
    )

    context = build_context(
        number=event.number,
        title=event.title,
        description=event.description,
        author=event.author,
        base_branch=event.base_branch,
        head_branch=event.head_branch,
        labels=event.labels,
        changed_files=event.changed_files,
        draft=event.draft,
    )
    print(f"injection    : {context.flagged_fields() or 'none'}")
    print(f"file kinds   : {sorted(context.state['pull_request']['file_categories'])}\n")

    settings = Settings()
    api_key, base_url = settings.jev_credentials()
    provider = JevDecisionProvider(
        api_key,
        settings.jev_model,
        base_url=base_url,
        transport_name=settings.jev_transport,
    )
    pipeline = DecisionPipeline(
        provider, load_registry(), is_official_jev=provider.is_official_jev
    )
    try:
        run = await pipeline.evaluate(event, context)
    finally:
        await provider.close()

    print(f"status       : {run.status.value}  ({run.latency_ms} ms)")
    if not run.succeeded:
        print(f"error        : {run.error}")
        return 3

    print("\ndecisions")
    for name, answer in run.answers.items():
        if isinstance(answer, ChoiceAnswer):
            print(f"  {name:24} {answer.choice} (confidence {answer.confidence:.2f})")
        elif isinstance(answer, ScoreAnswer):
            print(
                f"  {name:24} {answer.score:.2f} -> level {answer.resolve_level()} "
                f"(confidence {answer.confidence:.2f})"
            )
        else:
            print(f"  {name:24} {answer.noul:.2f}")

    actions = pipeline.plan_actions(run)
    print("\nactions justified")
    for action in actions:
        print(f"  {action['action_type']:16} {action['target']}")
    if not actions:
        print("  (none)")

    engine = create_engine(DB_URL)
    await create_schema(engine)
    async with session_scope(engine) as session:
        await AuditStore(session).record_run(event, run, actions)
    await engine.dispose()
    print(f"\nrecorded in  : {DB_URL}")

    if not token:
        print("\nno GITHUB_TOKEN set, so no label was applied.")
        return 0

    executor = GitHubActionExecutor(token)
    try:
        for action in actions:
            result = await executor.perform(
                action, repository=event.repository, number=event.number
            )
            print(f"  {result.status:10} {result.action_type:16} {result.detail}")
    finally:
        await executor.close()

    final = fetch_json(
        f"https://api.github.com/repos/{repository}/issues/{number}/labels", token
    )
    print(f"\nlabels on PR: {', '.join(label['name'] for label in final) or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))