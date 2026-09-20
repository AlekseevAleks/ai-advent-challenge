"""Task state machine: the formalised position of a task.

Kept separate from the memory layers:

* short-term memory — the current dialogue;
* working memory    — free-form context about the task;
* long-term memory  — durable facts about the user;
* **task state**    — stage / current step / expected action / status.

:class:`backend.tasks.manager.TaskStateManager` is the only way to change it.
"""

from __future__ import annotations

from backend.tasks.models import (
    ALLOWED_TRANSITIONS,
    STAGE_LABELS,
    STAGE_ORDER,
    STATUS_LABELS,
    Stage,
    Status,
    TaskPauseRequest,
    TaskState,
    TaskStateCreate,
    TaskStateData,
    TaskStateList,
    TaskStateUpdate,
    TaskStepSuggestion,
    TaskTransitionRequest,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "STAGE_LABELS",
    "STAGE_ORDER",
    "STATUS_LABELS",
    "Stage",
    "Status",
    "TaskPauseRequest",
    "TaskState",
    "TaskStateCreate",
    "TaskStateData",
    "TaskStateList",
    "TaskStateUpdate",
    "TaskStepSuggestion",
    "TaskTransitionRequest",
]