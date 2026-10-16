---
name: gatewise-review
description: Review a pull request in the Gatewise repository — the repo-specific checklist (fail-closed decisions, executor allowlist, webhook order, untrusted-input surface) plus the evidence block to post. Use when the user asks to review a PR, a diff, or check code correctness here.
argument-hint: "[owner/repo#number]"
---

# Gatewise PR review

## Steps

1. Read `@docs/agents/reviews.md` — it is the playbook; follow its order:
   hardcheck the six invariants first, then quality gates, then the diff.
2. For an open GitHub PR, fetch the view: `gh pr view <number> --json title,body`
   and `gh pr diff <number>`; keep `owner/repo#number` from the arguments.
3. Post the evidence block from the playbook (tests/ruff/mypy real numbers,
   fallback `none`, allowlist `untouched`, webhook order `intact`).

## Pitfalls

- Never merge; a human reviews and merges. Agents prepare.
- A silent refactor of `ALLOWED_ACTIONS`/webhook order is an automatic reject
  regardless of green tests.
