"""Run one simulated PR through the full pipeline against the REAL Jev model.

    python scripts/smoke_pipeline.py

This is the honest end-to-end check: real context, real signature verification,
real model call, real action plan. It prints the action plan but executes nothing,
since GitHub API execution needs an installation token.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, "packages")

from dotenv import load_dotenv

load_dotenv()

from actions import DecisionPipeline
from config import Settings
from context import build_context
from decisions.jev import JevDecisionProvider
from decisions.registry import load_registry
from github import compute_signature, parse_pull_request_event, verify_signature

SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET") or "local-smoke-secret"


def build_payload():
    return json.dumps(
        {
            "action": "opened",
            "repository": {"full_name": "octo/repo"},
            "pull_request": {
                "number": 5215,
                "title": "Rotate the production database credentials",
                "body": (
                    "Rotates the DB password used by the payments service and "
                    "updates the secret reference in the deployment manifests."
                ),
                "user": {"login": "octocat"},
                "base": {"ref": "main"},
                "head": {"ref": "chore/rotate-creds", "sha": "deadbeef"},
                "labels": [],
                "draft": False,
                "changed_files_list": [
                    {"filename": "deploy/secrets.yaml"},
                    {"filename": "services/payments/db.py"},
                ],
            },
        }
    ).encode("utf-8")


async def main() -> int:
    try:
        settings = Settings()
        api_key, base_url = settings.jev_credentials()
    except RuntimeError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    body = build_payload()

    # 1. Verify the signature exactly as the endpoint would.
    verify_signature(body, compute_signature(body, SECRET), SECRET)
    print("signature      : verified")

    event = parse_pull_request_event(body, event="pull_request")
    context = build_context(
        number=event.number,
        title=event.title,
        description=event.description,
        author=event.author,
        base_branch=event.base_branch,
        head_branch=event.head_branch,
        labels=event.labels,
        changed_files=event.changed_files,
    )
    print(f"pull request   : {event.repository}#{event.number}")
    print(f"injection flags: {context.flagged_fields() or 'none'}")
    print()

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

    print(f"transport      : {provider.transport}  (official jev: {provider.is_official_jev})")
    print(f"status         : {run.status.value}  ({run.latency_ms} ms)")
    print(f"state hash     : {run.state_hash[:16]}...")
    print(f"questions      : {', '.join(run.question_versions)}")
    if run.error:
        print(f"error          : {run.error}")
        return 3

    print("\ndecisions")
    from decisions.schemas import ChoiceAnswer, ScoreAnswer

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

    print("\naction plan (not executed)")
    actions = pipeline.plan_actions(run)
    if not actions:
        print("  (no actions justified)")
    for action in actions:
        print(f"  {action['action_type']:16} {action['target']:16} {action['fingerprint'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
