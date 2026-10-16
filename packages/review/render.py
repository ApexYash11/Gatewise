"""Render a :class:`review.loop.ReviewResult` as plain text.

One renderer, two consumers: the CLI prints exactly this, and later the GitHub
Action hoists this same output into the PR comment. Fractions of the report are
never re-rendered, so what a human sees on the terminal is what everyone sees on
a pull request — the review is not a different product depending on the surface.
"""

from __future__ import annotations

from decisions.schemas import ChoiceAnswer, ScoreAnswer

from review.loop import ReviewResult


def render_review(result: ReviewResult, *, execution_note: str | None = None) -> str:
    """Render the complete review report.

    Args:
        result: The outcome of :func:`review.loop.run_review`.
        execution_note: Overrides the "why nothing was executed" line, for
            example when ``--no-execute`` was passed with a token present.
    """
    event, run, context = result.event, result.run, result.context
    lines = [
        f"pull request : {event.repository}#{event.number}  {event.title}",
        f"changed files: {len(event.changed_files)}",
        f"injection    : {context.flagged_fields() or 'none'}",
        "file kinds   : "
        + ", ".join(sorted(context.state["pull_request"]["file_categories"])),
        "",
        f"status       : {run.status.value}  ({run.latency_ms} ms)",
    ]

    if not run.succeeded:
        lines.append(f"error        : {run.error or 'unknown error'}")
        lines.append("")
        lines.append("run recorded; no decision, so no action was authorized.")
        return "\n".join(lines)

    lines.append("")
    lines.append("decisions")
    for name, answer in run.answers.items():
        if isinstance(answer, ChoiceAnswer):
            lines.append(
                f"  {name:24} {answer.choice} (confidence {answer.confidence:.2f})"
            )
        elif isinstance(answer, ScoreAnswer):
            lines.append(
                f"  {name:24} {answer.score:.2f} -> level {answer.resolve_level()} "
                f"(confidence {answer.confidence:.2f})"
            )
        else:
            lines.append(f"  {name:24} {answer.noul:.2f}")

    lines.append("")
    lines.append("actions justified")
    if not result.actions:
        lines.append("  (none)")
    else:
        for action in result.actions:
            lines.append(f"  {action['action_type']:16} {action['target']}")
        if result.action_results:
            lines.append("")
            lines.append("actions applied")
            for applied in result.action_results:
                lines.append(f"  {applied.status:10} {applied.action_type:16} {applied.detail}")
        elif execution_note:
            lines.append(f"  ({execution_note})")

    lines.append("")
    lines.append(f"recorded in  : {result.database_url}")
    return "\n".join(lines)
