"""Action routing and the decision pipeline.

:class:`actions.pipeline.DecisionPipeline` orchestrates a single pull request
evaluation and produces a fully auditable :class:`~actions.pipeline.EvaluationRun`.

:class:`~actions.pipeline.DecisionPipeline.plan_actions` translates a run's typed
decisions into a deterministic action plan. Policy lives here, in application
code, and is expressed in levels and probability bands -- never exact floats,
because Jev is non-deterministic.

Deliberately excluded for now, pending explicit safeguards: ``merge``,
``delete``, ``force_push``, ``release`` and ``deployment``.

Executing actions against the GitHub API is not implemented: it needs a GitHub App
installation token. A plan is produced and recorded first, so the decision-to-action
link is auditable even before execution exists.
"""

from .pipeline import DecisionPipeline, EvaluationRun, RunStatus, hash_state

__all__ = [
    "DecisionPipeline",
    "EvaluationRun",
    "RunStatus",
    "hash_state",
]
