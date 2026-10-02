# Security Policy

## Supported versions

Gatewise is pre-1.0. Only the latest commit on `main` receives fixes.

| Version | Supported |
| --- | --- |
| `main` | Yes |
| Anything older | No |

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.** A public issue
tells everyone about the bug before it is fixed.

Report it privately through GitHub's **Report a vulnerability** button under the
repository's `Security` tab. That opens a private advisory visible only to the
maintainer.

Please include:

- What the issue is and what an attacker could achieve.
- The affected file or endpoint, and the version or commit.
- Steps to reproduce, ideally a pull request body, webhook payload, or API request.
- What you already tried, so it can be ruled out.

You can expect an acknowledgement within a few days. If a report turns out not to
be a vulnerability, that is fine — say so and it will be closed without judgement.

## Scope worth reporting

These are the boundaries Gatewise is designed around, so a break in one matters:

- **Untrusted input crossing into decision context.** Pull request titles, bodies,
  branch names, and file paths are attacker-controlled. Any way to make that text
  steer the decision instructions, override the rubric, or change the system role
  is a genuine finding. `tests/adversarial/` is the existing regression net.
- **Webhook signature verification.** Any path that accepts an unsigned or
  wrongly-signed delivery, or that replays a previously accepted one.
- **Credential handling.** A key, token, or webhook secret appearing in logs, an
  API response, a stored run, or model context. `Settings.safe_summary()` reports
  presence only, and must keep doing so.
- **A fake decision.** Any code path that substitutes a heuristic, keyword match, or
  default value for a real model answer, or that converts a provider failure into
  `risk = 0` / `safe = true`. This is the project's single most important
  invariant — see `CONTRIBUTING.md`.

## Not vulnerabilities

- The model returning a decision you disagree with. Decisions are recorded with the
  question version they were asked under, and disagreement is not a defect.
- `scripts/review_pr.py` and `scripts/apply_action.py` writing to GitHub. That is
  their documented purpose, and it requires an explicitly configured token.
- The bundled evaluation dataset's labels being weak. They are described as
  assistant-assessed in the README, and no accuracy claim is made.
- Missing rate limiting on a local-only development server.