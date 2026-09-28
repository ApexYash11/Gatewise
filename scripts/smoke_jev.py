"""Live smoke check against the real Jev API.

Run with a real key to confirm end-to-end operation:

    set TYPESAFE_API_KEY=sk-...
    python scripts/smoke_jev.py

Without a key this exits non-zero and explains what is missing. It never falls
back to a simulated decision.
"""

import asyncio
import sys

sys.path.insert(0, "packages")

from context import build_context
from decisions.jev import JevDecisionProvider
from decisions.provider import DecisionUnavailable
from decisions.registry import load_registry
from decisions.schemas import ChoiceAnswer, NoulAnswer, ScoreAnswer


async def main() -> int:
    try:
        from config import Settings

        settings = Settings()
        api_key, base_url = settings.jev_credentials()
    except RuntimeError as exc:
        print(f"BLOCKED: {exc}")
        return 2

    ctx = build_context(
        number=5215,
        title="Upgrade the ingress controller",
        description="Bumps NGINX ingress 4.4.0 -> 4.9.0 and adjusts default timeouts.",
        author="octocat",
        base_branch="main",
        head_branch="chore/ingress-upgrade",
        labels=["dependencies"],
        changed_files=["deploy/helm/values.yaml", "test/e2e/ingress_test.py"],
        diff="--- a/values.yaml\n+++ b/values.yaml\n- timeout: 30\n+ timeout: 60\n",
    )

    provider = JevDecisionProvider(
        api_key,
        settings.jev_model,
        base_url=base_url,
        transport_name=settings.jev_transport,
    )
    try:
        answers = await provider.evaluate(ctx.state, load_registry().build_request())
    except DecisionUnavailable as exc:
        print(f"UNAVAILABLE: {exc}")
        return 3
    finally:
        await provider.close()

    print(f"transport: {provider.transport}")
    print(f"model:     {provider.model}\n")
    for name, answer in answers.items():
        if isinstance(answer, ChoiceAnswer):
            print(f"{name:26} {answer.choice} (confidence {answer.confidence:.2f})")
        elif isinstance(answer, ScoreAnswer):
            label = answer.level_label() or ""
            print(
                f"{name:26} {answer.score:.2f} -> level {answer.resolve_level()} "
                f"[{label}] (confidence {answer.confidence:.2f})"
            )
        elif isinstance(answer, NoulAnswer):
            print(f"{name:26} {answer.noul:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
