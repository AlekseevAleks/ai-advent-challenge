"""Invariants: mandatory constraints on the space of allowed solutions.

Kept separate from the other layers:

* profile     — how the assistant answers;
* memory      — what is known;
* task state  — where the task is;
* **invariant** — which solutions are not allowed.

:class:`backend.invariants.manager.InvariantManager` is the only way to change
them, and :class:`backend.invariants.detector.InvariantConflictDetector`
proposes conflicts for the manager to validate.
"""

from __future__ import annotations

from backend.invariants.models import (
    CATEGORY_LABELS,
    GLOBAL_SCOPE_ID,
    PRIORITY_LABELS,
    PRIORITY_ORDER,
    Category,
    ConflictCheckResult,
    Invariant,
    InvariantConflict,
    InvariantCreate,
    InvariantData,
    InvariantList,
    InvariantUpdate,
    Priority,
    Scope,
    Status,
)

__all__ = [
    "CATEGORY_LABELS",
    "GLOBAL_SCOPE_ID",
    "PRIORITY_LABELS",
    "PRIORITY_ORDER",
    "Category",
    "ConflictCheckResult",
    "Invariant",
    "InvariantConflict",
    "InvariantCreate",
    "InvariantData",
    "InvariantList",
    "InvariantUpdate",
    "Priority",
    "Scope",
    "Status",
]
