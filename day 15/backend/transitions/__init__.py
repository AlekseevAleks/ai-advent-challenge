"""The configurable task lifecycle: states, transition rules and history.

This package is a layer of its own, next to memory, profile, task state and
invariants:

* :mod:`backend.transitions.models` — the schemas and the condition vocabulary;
* :mod:`backend.transitions.conditions` — the safe condition evaluator;
* :mod:`backend.transitions.manager` — the only way to change the lifecycle;
* :mod:`backend.transitions.detector` — the model that *proposes* a transition.

The manager is re-exported lazily: the repository layer imports the models from
this package, so importing the manager eagerly here would close a cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.transitions.manager import (
        DuplicateRuleError,
        InvalidRuleError,
        StateInUseError,
        TransitionManager,
        TransitionRejectedError,
    )

__all__ = [
    "DuplicateRuleError",
    "InvalidRuleError",
    "StateInUseError",
    "TransitionManager",
    "TransitionRejectedError",
]


def __getattr__(name: str) -> Any:
    """Resolve the manager symbols on first use, avoiding an import cycle."""
    if name in __all__:
        from backend.transitions import manager

        return getattr(manager, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
