---
name: gatewise-triage
description: Run Gatewise's typed, auditable decision pass on a GitHub pull request before inspecting its changes. Use when asked to triage or assess a PR with Gatewise.
---

# Gatewise pull request triage

Use this skill when the user asks for a Gatewise assessment of a pull request.
Run it before reading the PR diff so the decision is based on the submitted
context, not on an agent's prior review.

## Run

The Gatewise CLI must be installed (`pip install gatewise`) and configured with
`TYPESAFE_API_KEY` or `OPENROUTER_API_KEY`. For a public PR, run:

```sh
gatewise review OWNER/REPOSITORY NUMBER --no-execute
```

For a private repository, configure `GITHUB_TOKEN` with read access as well.
Do not put credentials in command arguments, PR context, or output.

## Report

- Summarize the CLI's typed decisions and any planned actions.
- State clearly if the CLI exits with an error; never invent missing answers or
  turn a failed run into a low-risk result.
- Keep the assessment separate from any later code inspection. Gatewise is a
  decision layer, not a code review.
- `--no-execute` records and reports the plan without writing to GitHub. Only
  run without that flag when the user explicitly asks to execute Gatewise's
  planned actions.
