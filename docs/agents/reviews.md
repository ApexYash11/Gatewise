# Reviewing PRs in Gatewise

How to review a pull request — in this repo — without losing the properties the
codebase exists to keep. Trigger this playbook on any review request; the
`/gatewise-review` skill points here.

## Hardways a good PR can still be wrong

Check these *every time*; each one has broken real projects and none is caught
by tests alone:

1. **No fallback creep.** Search the diff for anything that could stand in for a
   decision: keyword counting, default `risk`, `safe = true` on error, `except`
   that swallows `DecisionUnavailable`. A provider failure must remain a
   recorded failure (`RunStatus.FAILED`, error kept on the run).
2. **Executor allowlist untouched.** `packages/actions/executor.py`'s
   `ALLOWED_ACTIONS`/`FORBIDDEN_ACTIONS` must not have changed shape. Anything
   that teaches the executor to merge, delete, force-push, release, or deploy is
   an automatic reject.
3. **Webhook order intact.** Signature verification happens before
   deduplication, deduplication before parsing, parsing before context. Reorder
   in `apps/api/app/main.py` or `packages/actions/pipeline.py` is an automatic
   reject — the order is a security property, not a style choice.
4. **Untrusted-input surface.** If the diff makes new text reach the model
   (builder fields, fetch data, comment rendering), there must be adversarial
   coverage under `tests/adversarial/` for it in the same PR.
5. **Question versions.** If `packages/decisions/questions/pull_request.yaml`
   changed without a version bump, reject. See `questions.md`.
6. **Nothing leaked.** New env var decoding? Tokens printed? A URL built with
   unvalidated repository input (must pass `validate_repository`)? Check the
   security model in `AGENTS.md`.

## Quality gates (already automated, still read them)

- `pytest -q` green with no network and no API key.
- `ruff check .` and `mypy` clean — CI runs the `lint` job; reviewer confirms
  locally after the last edit, not at the start of the session.
- New behavior has a test that fails without the change.

## Read the diff like this

1. **Audit trail first.** Does a failing run still get recorded
   (`AuditStore.record_run` on every path)? An unrecorded failure is
   indistinguishable from silence — both hide the system not working.
2. **Test boundaries.** Tests must stub the *network* (`RecordingTransport`,
   `httpx.MockTransport`, injected clients), never the model's judgement. A test
   that hard-codes "this PR is high risk" without a payload from the real
   contract is simulating intelligence — reject it.
3. **Minimal diff.** No drive-by reformat. If unrelated formatting appears,
   ask the author to split it.
4. **Docstrings.** New modules should record constraints a reader could not
   infer (the `#/` attribute comments and module headers are the house style,
   modeled on `packages/review/loop.py`); narration-style comments are noise.

## Evidence format for the review comment

Append to the PR or reply, short and factual:

```
- `{n}` tests pass: `pytest -q` (no network, no API key)
- ruff/mypy: clean / (finding at `file:line`)
- Gatewise checks: fallback `none`, allowlist `untouched`, webhook order `intact`
- Untrusted surface: unchanged / (adversarial coverage in `tests/adversarial/...`)
```

Do not merge without these lines filled in. Do not merge at all — a human
(owner or maintainer) merges; agents prepare.
