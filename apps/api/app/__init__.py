"""Gatewise HTTP API.

Exposes the webhook receiver and read endpoints over the decision pipeline and
audit store. The service layer holds all decision logic so the same behaviour is
reachable from HTTP, from a script, or from a test.
"""

__all__: list[str] = []
