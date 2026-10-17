"""The serverless review path: fetch -> decide -> record -> execute.

The webhook server is one way to reach the decision pipeline, and it will stay
that way. But a review must not require a running server: anyone — a maintainer,
a GitHub Action, a coding agent — should be able to ask one function for the same
result the webhook path produces.

``run_review`` is that entry point. It fetches the real pull request over the
GitHub API, builds the isolated context, asks the real decision model, records
every decision evaluation in the audit store once the pull request has been
fetched and the provider is configured, and only then performs the actions the
run justifies, behind an explicit token and the executor's allowlist.

Exit-code meaning is owned by :mod:`gatewise.review.cli`. The loop returns a
result for every evaluation outcome — a failed run recorded honestly is a
result, not an error to hide; fetch and configuration failures raise instead,
because there is no run to show for them.
"""

from .cli import main
from .loop import ReviewResult, run_review
from .render import render_review

__all__ = ["ReviewResult", "main", "render_review", "run_review"]
