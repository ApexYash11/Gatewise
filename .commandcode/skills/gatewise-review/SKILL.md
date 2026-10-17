---
name: gatewise-review
description: Review a pull request in the Gatewise repository — the repo-specific checklist (fail-closed decisions, executor allowlist, webhook order, untrusted-input surface) plus the evidence block to post. Use when the user asks to review a PR, a diff, or check code correctness here.
argument-hint: "[owner/repo#number]"
---

# Gatewise PR review

## Steps

1. Fetch the diff first — every check below searches it:
   `gh pr view <number> --repo <owner/repo> --json title,body` and
   `gh pr diff <number> --repo <owner/repo>`, taking `owner/repo` from the
   `owner/repo#number` argument. Pass `--repo`: without it `gh` reads the local
   clone's repository, not the one named in the argument.
2. Read `@docs/agents/reviews.md` — the playbook; sweep in its order: the six
   invariants against the fetched diff, then the quality gates, then the diff.
3. Post the evidence block from the playbook (tests/ruff/mypy real numbers,
   fallback `none`, allowlist `untouched`, webhook order `intact`).

## Pitfalls

- Never merge; a human reviews and merges. Agents prepare.
- A silent refactor of `ALLOWED_ACTIONS`/webhook order is an automatic reject
  regardless of green tests.
