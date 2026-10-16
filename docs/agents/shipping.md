# Shipping work in Gatewise

The standing workflow every task follows. The `/ship-work` skill points here.

## The loop

1. **Raise the work as an issue.** One issue per phase/task, `enhancement` for
   features and improvements, `bug` for breakage, `documentation` for docs. The
   body states *what / why / definition of done* with checkboxes.
2. **Branch from the current `main` state:**
   `git checkout -b feat/<short-name>`. One branch per issue; no long-lived
   mega-branches.
3. **Implement** with minimal diffs. Architecture must stay inside the
   boundaries in `AGENTS.md`; a boundary you cannot respect is a breaking point
   (see below), not a quick refactor.
4. **Verify (never skip):**
   - `.venv\Scripts\python -m pytest -q` — all green, no network used
   - `ruff check .` — clean
   - `mypy` — clean
   - For skill/docs work: `cmd skills list` shows the skills, no load failures
   Run these **after your last edit**, and paste real numbers as evidence — not
   "should be green".
5. **Commit:** message states the change in one line, its constraint in two, and
   ends with `Closes #<issue>`. Never `git add -A` blindly — `.commandcode/`
   local state (taste, scratch) stays untracked.
6. **Push and open the PR** with three sections:
   - *What* — 2–6 bullets of behavior change
   - *Review guide* — where to start reading, flags like allowlist/webhook notes
   - *Test evidence* — the verify output lines
7. **Hand over for review.** The user tests and reviews; **merge is always the
   user's action**. Address feedback on the same branch, re-verify, re-push.

## Breaking points

When a real blocker appears (structure prevents the fix, boundary conflicts
with the task): stop implementing workarounds. Report it as its own issue
describing the conflict, propose options, and let the user choose a direction.
Work continues only after the decision is recorded on that issue.

## Phase mapping (current)

| Issue | Phase | Status |
|---|---|---|
| #2 | CLI + lint CI (phase 0) | PR #3 open for review |
| #4 | PyPI packaging (phase 1) | pending |
| #6 | GitHub Action (phase 2) | pending |
| #5 | npm skill package (phase 3) | pending |
| #7 | Human-labelled dataset (phase 4) | parallel, small set |

Keep this table updates-free: link new phase issues in the same style; details
live in `distribution.md`.
