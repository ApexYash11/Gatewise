"""Action routing.

Not yet implemented. Initial actions will be ``add_label``, ``comment``,
``request_review`` and ``trigger_workflow``.

Deliberately excluded for now, pending explicit safeguards: ``merge``, ``delete``,
``force_push``, ``release`` and ``deployment``.

Design constraints already established:
- actions are selected by *policy over decisions*, never by heuristic code;
- every action carries a deterministic identifier derived from the decision run, so
  a redelivered webhook cannot produce a duplicate action;
- if the decision run failed, no action executes.
"""

__all__: list[str] = []
