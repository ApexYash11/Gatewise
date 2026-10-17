---
name: verify
description: Pre-merge verification gate for Gatewise — run the real test/lint/type suite after the last edit and report actual counts as evidence. Use before claiming any change is green, before opening a PR, or when asked "is it green / does it pass / test it".
---

# Verify before claiming green

## Steps

1. After your **last** edit (not earlier), run from the repo root:
   ```bash
   # Windows (PowerShell or cmd)
   .venv\Scripts\python -m pytest -q
   .venv\Scripts\python -m ruff check . --output-format concise
   .venv\Scripts\python -m mypy

   # macOS / Linux
   .venv/bin/python -m pytest -q
   .venv/bin/python -m ruff check . --output-format concise
   .venv/bin/python -m mypy
   ```
   Always use the repo venv interpreter (`.venv\Scripts\python` or
   `.venv/bin/python`) — never bare `python`, which may differ at the PATH.
   For skill/docs work also run: `cmd skills list` (no load failures).
2. If anything fails, fix it and rerun until green. Never leave broken code.
3. Report as evidence (numbers only, no "should pass"):
   `<n from the run> passed · ruff clean · mypy clean · skills: N loaded`

## Pitfalls

- Running tests before the last edit and assuming the suite still green.
- Building or shipping without the run; "the change is docs-only" still gets
  verified (pytest, ruff fast).
- Never simulate the results; the `/gatewise-review` consumer expects real counts.
