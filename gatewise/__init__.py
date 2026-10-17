"""Gatewise: decision infrastructure for autonomous software engineering.

The namespace exists so everything installs under one importable package.
Historically the packages installed as top-level modules (``github``,
``actions``, ``config``...), which collides with existing names on PyPI —
the rename is the gate for publishing (issue #4). The house rules live in
``AGENTS.md``; the architectural one to know here: everything above
:mod:`gatewise.decisions.provider` depends only on the abstract provider,
never on Jev.
"""

__version__ = "0.2.0"
