"""Evaluate a real pull request end to end: fetch, decide, record, label.

    set GITHUB_TOKEN=... OPENROUTER_API_KEY=...
    python scripts/review_pr.py ApexYash11/Gatewise 1

This is a thin launcher for the installed command:

    gatewise review ApexYash11/Gatewise 1

The full loop lives in ``packages/review``: fetch the real pull request,
build the isolated context, ask the real Jev model, record the run, then
perform only the actions the run justifies. Fetching a public repository
needs no token; performing actions does. Exit codes: 0 reviewed, 2 usage,
3 model unavailable, 4 fetch failed, 5 provider not configured.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "packages"))

from review.cli import main  # noqa: E402

if __name__ == "__main__":
    # The CLI routes through subcommands; the script always means "review".
    raise SystemExit(main(["review", *sys.argv[1:]]))
