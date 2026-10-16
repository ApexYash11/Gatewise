---
name: ship-work
description: The Gatewise branch/issue/PR shipping loop — raise work as an issue, branch it, verify, PR with What/Review guide/Test evidence, hand to the user for merge. Use when the user says ship, open the PR, deliver this phase, continue the loop, or closes a phase.
argument-hint: "[phase-or-task]"
---

# Ship the work

## Steps

1. Read `@docs/agents/shipping.md` — the full loop. Map the task to its issue
   (or raise one: `gh issue create --label enhancement`).
2. Branch: `git checkout -b feat/<short-name>`; implement minimal diffs.
3. Run the `/verify` skill last: pytest, ruff, mypy (and `cmd skills list` for
   skill work).
4. Commit with a one-liner, constraint note, `Closes #<issue>`;
   never blanket `git add -A` (`.commandcode/` local state stays untracked).
5. Push and `gh pr create` with *What / Review guide / Test evidence*; hand to
   the user for review and merge.

## Pitfalls

- Merging to `main` yourself, pushing to unrelated remotes, or force-pushing.
- A breaking structural conflict: stop, raise its own issue, offer options —
  no workaround hacks.
