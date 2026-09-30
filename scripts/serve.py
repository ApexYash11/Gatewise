"""Start the Gatewise server and open the dashboard.

    python scripts/serve.py

Loads .env, creates the database if it is missing, and serves the API plus the
dashboard on http://127.0.0.1:8000.

This exists because the manual invocation needs four environment variables and a
PYTHONPATH, and getting any of them wrong fails in a way that is hard to read:
the server starts and then every request returns 503 "decision provider is not
configured". Loading the environment here means one command, and the failure
message names the missing variable.
"""

import os
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dotenv import load_dotenv  # noqa: E402

# ``override`` stays False on purpose: a variable already exported into the
# environment is a deliberate deployment choice and should win over a local file.
# The consequence is that a *stale* exported key silently shadows a rotated one in
# .env, which is exactly the failure this function reports below.
load_dotenv(ROOT / ".env")


def shadowed_keys() -> list[str]:
    """Names set in the environment that differ from the value in ``.env``.

    A rotated credential is the common case: the new key is written to ``.env``
    but an old copy is still exported in the shell, and because ``load_dotenv``
    does not override, the server keeps using the old one and reports a
    confusing provider error (expired key, no credits) rather than a config
    mistake. Surfacing the conflict at startup turns that into one clear line.
    """
    if not (ROOT / ".env").exists():
        return []
    import os

    from dotenv import dotenv_values

    conflicts = []
    for name, file_value in dotenv_values(ROOT / ".env").items():
        if file_value is None:
            continue
        env_value = os.environ.get(name)
        if env_value and env_value != file_value:
            conflicts.append(name)
    return conflicts


def preflight() -> list[str]:
    """Report configuration problems before uvicorn starts.

    Failing here is friendlier than starting a server that answers every request
    with a 503 and no explanation of why.
    """
    problems: list[str] = []
    for name in shadowed_keys():
        problems.append(
            f"{name} is set in your shell and differs from .env. The exported value "
            "wins, so the server is not using the key in .env. If you just rotated "
            f"this credential, clear it with: setx {name} \"\"  and reopen the shell."
        )
    if not (os.environ.get("TYPESAFE_API_KEY") or os.environ.get("OPENROUTER_API_KEY")):
        problems.append(
            "No decision-model key. Set TYPESAFE_API_KEY (or OPENROUTER_API_KEY) "
            "in .env, or in your user environment."
        )
    if not os.environ.get("GITHUB_WEBHOOK_SECRET"):
        problems.append(
            "No GITHUB_WEBHOOK_SECRET. The webhook endpoint rejects every delivery "
            "without it, which is correct, but it is worth knowing up front."
        )
    return problems


def main() -> int:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))

    print(f"gatewise  ->  http://{host}:{port}")
    print(f"database  ->  {os.environ.get('DATABASE_URL', 'sqlite+aiosqlite:///./gatewise.db')}")

    for problem in preflight():
        print(f"\nwarning: {problem}")
    if any("No decision-model key" in p for p in preflight()):
        print("\nThe dashboard will render, but evaluations will fail closed.")
        print("That is intentional: Gatewise never invents a decision.\n")

    import uvicorn

    if "--open" in sys.argv:
        webbrowser.open(f"http://{host}:{port}")

    uvicorn.run("app.main:app", host=host, port=port, reload="--reload" in sys.argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
