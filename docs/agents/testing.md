# Testing conventions in Gatewise

The `/verify` skill and `AGENTS.md` testing standards point here for depth.

## The one rule that shapes everything

Stub the **network boundary** only. Never simulate the model's judgement.

- Allowed: fake transports, fake HTTP clients, injected providers/processes.
- Forbidden: tests where the "AI" part is a local heuristic (keyword list that
  yields risk 4, or risk parsed from a fixture title) — that protects the house
  rule that no fake intelligence exists, ever.

Existing boundary patterns to reuse:

- `tests/conftest.py::RecordingTransport` — canned `typesafe_sdk` response,
  records requests. Use for every Jev-provider test.
- `httpx.MockTransport` handlers — GitHub API fakes (see
  `tests/integration/test_review_loop.py`).
- Constructor injection — `fetch_pull_request(client=...)`,
  `GitHubActionExecutor(client=...)`, `run_review(github_client=...)`,
  `run_review(decision_provider=...)` exist precisely so tests never touch the
  network. Extend this pattern for new IO.

## Conventions

- **pytest-asyncio auto mode**: async tests just work; no markers needed.
- **Location mirrors source**: `github/fetch.py` → `test_fetch.py` (unit vs
  integration via the corresponding directory).
- **Parametrize** similar inputs instead of copy-pasting tests.
- **Fixtures**: shared shape fixtures belong in `tests/conftest.py`
  (`real_jev_payload` is the verified Jev response shape — reuse, do not
  re-derive).
- **A failing behavior needs a test that fails without the fix.** Run the new
  test against unpatched code once if you are unsure.
- **No hardcoded verdicts from prose**: context-builder heuristics (file
  categories) may be asserted as *descriptive labels*, never as risk levels.
- **Security properties get unit tests**, not just integration ones: signature
  tampering, replay/dedup, payload size — `tests/unit/test_webhook_security.py`
  is the model.

## Adversarial coverage

Anything that lets PR-authored text reach the model (new context fields, new
fetch endpoints, new render surfaces) gets cases under `tests/adversarial/`:
injection attempts, neutered payloads, marker patterns
(`flagged_fields()`), and truncation. Minimal bar and non-negotiable.

## Evidence

The `/verify` skill's report is what CI and reviewers accept: test count from
`pytest -q`, `ruff check .` and `mypy` clean, both after the last edit.
