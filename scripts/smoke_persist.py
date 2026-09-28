"""Run a real PR context through the pipeline and persist it to SQLite.

    python scripts/smoke_persist.py

This is the honest end-to-end check with no stubbing: real Jev call, real
database, then a read-back to prove the run is reconstructable.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, "packages")

from dotenv import load_dotenv

load_dotenv()

from actions import DecisionPipeline
from audit import AuditStore, create_engine, create_schema, session_scope
from config import Settings
from context import build_context
from decisions.jev import JevDecisionProvider
from decisions.registry import load_registry
from github import parse_pull_request_event

DB_URL = os.environ.get("DATABASE_URL") or "sqlite+aiosqlite:///./gatewise.db"


def build_payload():
    return json.dumps(
        {
            "action": "opened",
            "repository": {"full_name": "walidboulanouar/awesome-jev-use-cases"},
            "pull_request": {
                "number": 25,
                "title": "Add jev-engineering (Claude Code tool-call gate with auto mode)",
                "body": (
                    "Adds one entry to Open source -> Coding agents and developer tools. "
                    "Disclosure: I built and maintain this project."
                ),
                "user": {"login": "eugeniughelbur"},
                "base": {"ref": "main"},
                "head": {"ref": "add-jev-engineering", "sha": "c0ffee1"},
                "labels": [],
                "draft": False,
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

    engine = create_engine(DB_URL)
    await create_schema(engine)

    event = parse_pull_request_event(build_payload(), event="pull_request")
    context = build_context(
        number=event.number,
        title=event.title,
        description=event.description,
        author=event.author,
        base_branch=event.base_branch,
        head_branch=event.head_branch,
    )
    print(f"pull request : {event.repository}#{event.number}")
    print(f"injection    : {context.flagged_fields() or 'none'}")
    print(f"database     : {DB_URL}\n")

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

    actions = pipeline.plan_actions(run)
    async with session_scope(engine) as session:
        record = await AuditStore(session).record_run(event, run, actions)

    print(f"status       : {run.status.value} ({run.latency_ms} ms)")
    if run.error:
        print(f"error        : {run.error}")
        return 3

    # Read back from a fresh session to prove the run is reconstructable.
    async with session_scope(engine) as session:
        store = AuditStore(session)
        stored_pr = await store.get_pull_request(record.pull_request_id)
        stored_run = (await store.get_runs(stored_pr.id))[0]
        stored_decisions = await store.get_decisions(stored_run.id)
        stored_actions = await store.get_actions(stored_run.id)

    print(f"\npersisted run #{stored_run.id}")
    print(f"  provider    : {stored_run.provider} / {stored_run.model} "
          f"(official jev: {stored_run.is_official_jev})")
    print(f"  status      : {stored_run.status}")
    print(f"  state hash  : {stored_run.state_hash[:16]}...")
    print(f"  questions   : {', '.join(stored_run.question_versions)}")
    print(f"  latency     : {stored_run.latency_ms} ms")

    print("\npersisted decisions")
    for decision in stored_decisions:
        level = f" L{decision.level}" if decision.level is not None else ""
        confidence = (
            f" conf {decision.confidence:.2f}" if decision.confidence is not None else ""
        )
        print(f"  {decision.question_name:24} {decision.answer:>16}{level}"
              f"{confidence}  @{decision.question_version}")

    print("\npersisted actions")
    for action in stored_actions:
        print(f"  {action.action_type:16} {action.target:16} {action.fingerprint[:12]}")
    print(f"\ndatabase     : {DB_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
