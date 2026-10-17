"""Action routing and the decision pipeline.

:class:`actions.pipeline.DecisionPipeline` orchestrates a single pull request
evaluation and produces a fully auditable :class:`~actions.pipeline.EvaluationRun`.

:class:`~actions.pipeline.DecisionPipeline.plan_actions` translates a run's typed
decisions into a deterministic action plan. Policy lives here, in application
code, and is expressed in levels and probability bands -- never exact floats,
because Jev is non-deterministic.

Deliberately excluded for now, pending explicit safeguards: ``merge``,
``delete``, ``force_push``, ``release`` and ``deployment``.

Executing actions is :class:`actions.executor.GitHubActionExecutor`, which
performs only the four allowlisted types and refuses ``merge``, ``delete``,
``force_push``, ``release`` and ``deployment`` by construction.

One deliberate behaviour: the planner emits a sentinel reviewer target rather than
a username, because choosing *who* reviews is a policy question the model is not
asked. The executor skips it rather than guessing, so Gatewise never invents a
reviewer.
"""

from .executor import (
    ALLOWED_ACTIONS,
    FORBIDDEN_ACTIONS,
    ActionError,
    ActionNotPermitted,
    ActionResult,
    GitHubActionExecutor,
)
from .pipeline import DecisionPipeline, EvaluationRun, RunStatus, hash_state

__all__ = [
    "ALLOWED_ACTIONS",
    "FORBIDDEN_ACTIONS",
    "ActionError",
    "ActionNotPermitted",
    "ActionResult",
    "DecisionPipeline",
    "EvaluationRun",
    "GitHubActionExecutor",
    "RunStatus",
    "hash_state",
]
