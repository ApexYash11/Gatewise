"""Print the exact provider error, without printing any credential.

Run with a real key to see the precise failure:

    python scripts/diagnose_jev.py
"""

import asyncio
import os
import sys

sys.path.insert(0, "packages")

from decisions.jev import JevDecisionProvider
from decisions.registry import load_registry


async def main() -> int:
    key = ""
    source = ""

    # Prefer the local .env file, then the environment. The diagnostic must reflect
    # the same source the application would actually use.
    dotenv = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(dotenv):
        import re

        with open(dotenv, encoding="utf-8") as handle:
            match = re.search(
                r"(?m)^\s*(OPENROUTER_API_KEY|TYPESAFE_API_KEY)\s*=\s*(\S+)\s*$",
                handle.read(),
            )
        if match:
            key = match.group(2)
            source = f"{match.group(1)} (from .env)"

    if not key:
        key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or ""
        source = "environment variable"

    base_url = os.environ.get("TYPESAFE_BASE_URL") or (
        "https://openrouter.ai/api"
        if (os.environ.get("OPENROUTER_API_KEY") or os.path.exists(dotenv))
        else None
    )
    if not key:
        print("No API key found in .env or the environment.")
        return 2

    print(f"key source : {source}")
    print(f"key        : {key[:11]}...{key[-4:]} (len {len(key)})")
    print(f"base url   : {base_url or 'https://api.typesafe.ai (SDK default)'}")

    provider = JevDecisionProvider(
        key, base_url=base_url, transport_name="openrouter" if base_url else "typesafe"
    )
    try:
        answers = await provider.evaluate(
            {"state": "ping", "questions": {"ok": {"type": "noul"}}},
            {"ok": load_registry().get("pr_security_review").question},
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic tool, print everything
        print(f"\nERROR TYPE : {type(exc).__name__}")
        print(f"ERROR      : {exc}")
        cause = exc.__cause__
        if cause is not None:
            print(f"ROOT CAUSE : {cause}")
        return 3
    finally:
        await provider.close()

    print("\nSUCCESS")
    for name, answer in answers.items():
        print(f"  {name}: {answer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
