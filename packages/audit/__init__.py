"""Audit store.

Not yet implemented. Will persist repositories, pull requests, decision runs,
decisions, and actions per the schema in the specification.

Invariants for this package:
- a decision is stored together with the ``name@version`` of the question that
  produced it, so a rubric change never silently reinterprets history;
- secrets are never stored;
- a failed decision run is recorded as a failure with its error, not omitted and
  not stored as a low-risk result.
"""

__all__: list[str] = []
