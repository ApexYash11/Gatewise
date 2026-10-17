---
name: verify
description: Pre-merge verification gate for Gatewise — run the real test/lint/type suite after the last edit and report actual counts as evidence. Use before claiming any change is green, before opening a PR, or when asked "is it green / does it pass / test it".
---

# Verify before claiming green

## Steps

1. After your **last** edit (not earlier), run from the repo root:
   ```bash
   python -m pytest -q
   python -m ruff check . --output-format concise
   python -m mypy
   ```
   Invoke the repo venv interpreter explicitly: `.venv\Scripts\python.exe`
   on Windows, `.venv/bin/python` on macOS/Linux.
   For skill/docs work also run: `cmd skills list` (no load failures).
2. If anything fails, fix it and rerun until green. Never leave broken code.
3. Report as evidence (numbers only, no "should pass"):
   `<n from the run> passed · ruff clean · mypy clean · skills: N loaded`

## Pitfalls

- Running tests before the last edit and assuming the suite still green.
- Building or shipping without the run; "the change is docs-only" still gets
  verified (pytest, ruff fast).
- Never simulate the results; the `/gatewise-review` consumer expects real counts.
