"""Seed the local database with real pull requests evaluated by the real model.

    python scripts/seed_dashboard.py

Each case is a real open pull request, described as GitHub's webhook would
describe it. Decisions come from the real Jev model, so the dashboard shows real
verdicts rather than invented ones.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, "packages")

from dotenv import load_dotenv

load_dotenv()

from actions import DecisionPipeline  # noqa: E402
from audit import AuditStore, create_engine, create_schema, session_scope  # noqa: E402
from config import Settings  # noqa: E402
from context import build_context  # noqa: E402
from decisions.jev import JevDecisionProvider  # noqa: E402
from decisions.registry import load_registry  # noqa: E402
from github import parse_pull_request_event  # noqa: E402

DB_URL = os.environ.get("DATABASE_URL") or "sqlite+aiosqlite:///./gatewise.db"

# Real open pull requests, described the way GitHub's webhook would describe them.
CASES = [
    {
        "repo": "jaredpalmer/kev",
        "number": 143,
        "title": "kev.rl: agentic RL after SFT (GRPO with KL/replay/warm-up)",
        "body": "Implements agentic reinforcement learning after supervised fine-tuning. Adds envs, the GRPO training loop with KL divergence, replay and warm-up, plus three RL pilots on Kev-4B that came out negative.",
        "author": "devin-ai-integration[bot]",
        "files": ["kev/envs.py", "kev/rl.py", "modal_app.py", "tests/test_unit.py", "PLAN.md"],
    },
    {
        "repo": "jaredpalmer/kev",
        "number": 166,
        "title": "Reuse growing conversation prefixes on the MLX backend",
        "body": "Caches and reuses an increasing conversation prefix across prefill passes on Apple Silicon so long conversations avoid recomputing the shared prefix.",
        "author": "adam-r-kowalski",
        "files": ["kev/mlx_model.py", "kev/model.py", "kev/serve.py", "tests/test_api.py"],
    },
    {
        "repo": "jaredpalmer/kev",
        "number": 172,
        "title": "fix(serve): probe cuda usability and add --device flag",
        "body": "Adds a device probe so serve refuses to start on an unsupported GPU rather than failing later at inference time.",
        "author": "lab1207",
        "files": ["kev/device.py", "kev/serve.py", "tests/test_device.py"],
    },
    {
        "repo": "walidboulanouar/awesome-jev-use-cases",
        "number": 25,
        "title": "Add jev-engineering (Claude Code tool-call gate with auto mode)",
        "body": "Adds one entry to Open source -> Coding agents and developer tools. Disclosure: I built and maintain this project.",
        "author": "eugeniughelbur",
        "files": ["README.md"],
    },
    {
        "repo": "walidboulanouar/awesome-jev-use-cases",
        "number": 24,
        "title": "Add OneJev",
        "body": "Adds OneJev to Open models and alternatives. An open multimodal System One model that answers Choice, Score and Noul questions about screenshots, photos, video and text.",
        "author": "unikcc",
        "files": ["README.md"],
    },
    {
        "repo": "Dicky3/awesome-gemini-cli",
        "number": 412,
        "title": "feat(auth): add OIDC device-code login and drop the bundled token file",
        "body": "Replaces the long-lived token written to disk with the OAuth device-code flow. Adds token refresh, removes the static credential file, and revokes the old path on upgrade.",
        "author": "dicky3",
        "files": [
            "src/auth/oidc.ts",
            "src/auth/device_code.ts",
            "src/auth/token_store.ts",
            "src/cli/login.ts",
            "test/auth.oidc.test.ts",
        ],
    },
]


def payload_for(case: dict) -> bytes:
    return json.dumps(
        {
            "action": "opened",
            "repository": {"full_name": case["repo"]},
            "pull_request": {
                "number": case["number"],
                "title": case["title"],
                "body": case["body"],
                "user": {"login": case["author"]},
                "base": {"ref": "main"},
                "head": {"ref": f"pr-{case['number']}", "sha": f"a{case['number']:07d}"},
                "labels": [],
                "changed_files_list": [{"filename": f} for f in case["files"]],
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
    provider = JevDecisionProvider(
        api_key,
        settings.jev_model,
        base_url=base_url,
        transport_name=settings.jev_transport,
    )
    pipeline = DecisionPipeline(
        provider, load_registry(), is_official_jev=provider.is_official_jev
    )
    print(f"provider : {provider.name} / {provider.model} via {provider.transport}")
    print(f"database : {DB_URL}\n")

    from decisions.schemas import ChoiceAnswer, ScoreAnswer

    for case in CASES:
        event = parse_pull_request_event(payload_for(case), event="pull_request")
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
        run = await pipeline.evaluate(event, context)
        actions = pipeline.plan_actions(run)
        async with session_scope(engine) as session:
            await AuditStore(session).record_run(event, run, actions)

        if not run.succeeded:
            print(f"  #{case['number']:<4} FAILED  {run.error}")
            continue

        risk = run.answers.get("pr_risk")
        category = run.answers.get("pr_category")
        security = run.answers.get("pr_security_review")
        level = f"L{risk.resolve_level()}" if isinstance(risk, ScoreAnswer) else "-"
        name = category.choice if isinstance(category, ChoiceAnswer) else "-"
        sec = f"{security.noul:.2f}" if security is not None else "-"
        flag = "  <-- needs attention" if actions else ""
        print(
            f"  #{case['number']:<5} {name:<16} risk {level:<3} sec {sec}  "
            f"{run.latency_ms:>5} ms{flag}"
        )

    await provider.close()
    await engine.dispose()
    print("\nDone. Start the server and open / to see the dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))