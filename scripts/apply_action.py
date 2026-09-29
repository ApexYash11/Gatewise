"""Apply a planned action to a real pull request.

    set GITHUB_TOKEN=...
    python scripts/apply_action.py --repo owner/name --pr 123 --action add_label --target risk:high

Used to verify a token's permissions and to perform one real action. The token is
read from the environment and never written to a file or echoed.
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, "packages")

from dotenv import load_dotenv

load_dotenv()

from actions import GitHubActionExecutor  # noqa: E402

LABEL_COLORS = {
    "risk:high": "B60205",
    "security:review": "D93F0B",
    "testing:escalated": "FBCA04",
    "review:requested": "0E8A16",
}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--action", default="add_label")
    parser.add_argument("--target", required=True)
    parser.add_argument(
        "--create-label",
        action="store_true",
        help="Create the label first if the repository does not have it.",
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("BLOCKED: set GITHUB_TOKEN first")
        return 2

    executor = GitHubActionExecutor(token)
    try:
        if args.create_label and args.action == "add_label":
            color = LABEL_COLORS.get(args.target, "D4C5F9")
            import httpx

            async with httpx.AsyncClient(
                base_url="https://api.github.com",
                timeout=15.0,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            ) as setup:
                response = await setup.post(
                    f"/repos/{args.repo}/labels",
                    json={"name": args.target, "color": color, "description": "Applied by Gatewise"},
                )
                # 201 created, 422 already exists. Either is fine here.
                print(f"create label : HTTP {response.status_code}")

        result = await executor.perform(
            {"action_type": args.action, "target": args.target},
            repository=args.repo,
            number=args.pr,
        )
    finally:
        await executor.close()

    print(f"action       : {result.action_type}")
    print(f"status       : {result.status}")
    print(f"detail       : {result.detail}")
    if result.http_status:
        print(f"http         : {result.http_status}")
    return 0 if result.status in {"performed", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
