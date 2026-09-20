"""Pydantic schemas for the task state machine.

The task state is a *formalised* description of where a task stands. It is a
different thing from working memory:

* working memory — free-form context about the task (stack, requirements, …);
* task state     — the finite-state-machine position: stage, current step,
  expected action and status.

It is stored in its own table and only ever changed through
:class:`backend.tasks.manager.TaskStateManager`, which validates transitions.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, computed_field, field_validator

#: The stages of the task lifecycle, in order.
Stage = Literal["planning", "execution", "validation", "done"]

#: ``paused`` is a status, not a stage: a paused task keeps its stage.
Status = Literal["active", "paused", "completed"]

#: Ordered stages, used to render progress and to validate forward moves.
STAGE_ORDER: tuple = ("planning", "execution", "validation", "done")

#: Allowed stage transitions. A task may only move along these edges.
ALLOWED_TRANSITIONS: dict = {
    "planning": ("execution",),
    "execution": ("validation",),
    "validation": ("done",),
    "done": (),
}

STAGE_LABELS = {
    "planning": "Planning",
    "execution": "Execution",
    "validation": "Validation",
    "done": "Done",
}

STATUS_LABELS = {
    "active": "Active",
    "paused": "Paused",
    "completed": "Completed",
}


class TaskStateData(BaseModel):
    """The formalised state of one task."""

    stage: Stage = "planning"
    current_step: str = ""
    expected_action: str = ""
    status: Status = "active"
    previous_stage: Optional[Stage] = None
    pause_reason: str = ""
    completed_steps: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @field_validator("current_step", "expected_action", "pause_reason")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("completed_steps")
    @classmethod
    def _clean_steps(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    def is_paused(self) -> bool:
        return self.status == "paused"

    def is_completed(self) -> bool:
        return self.status == "completed" or self.stage == "done"


class TaskState(BaseModel):
    """A stored task state, as returned by the API."""

    task_id: str
    chat_id: str
    data: TaskStateData = Field(default_factory=TaskStateData)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    exists: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress(self) -> List[dict]:
        """Stage list with a marker for the UI: done / current / pending."""
        current_index = STAGE_ORDER.index(self.data.stage)
        items: List[dict] = []
        for index, stage in enumerate(STAGE_ORDER):
            if index < current_index or self.data.stage == "done":
                marker = "done"
            elif index == current_index:
                marker = "current"
            else:
                marker = "pending"
            items.append(
                {
                    "stage": stage,
                    "label": STAGE_LABELS[stage],
                    "marker": marker,
                }
            )
        return items


class TaskStateCreate(BaseModel):
    """Payload for creating a task state."""

    stage: Stage = "planning"
    current_step: str = ""
    expected_action: str = ""
    metadata: dict = Field(default_factory=dict)


class TaskStateUpdate(BaseModel):
    """Payload for updating the descriptive fields of a task state.

    Stage and status are deliberately absent: they may only change through
    ``transition`` / ``pause`` / ``resume`` / ``complete``.
    """

    current_step: Optional[str] = None
    expected_action: Optional[str] = None
    metadata: Optional[dict] = None

    @field_validator("current_step", "expected_action")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


class TaskTransitionRequest(BaseModel):
    """Payload for an explicit stage transition."""

    stage: Stage
    current_step: Optional[str] = None
    expected_action: Optional[str] = None
    reason: str = ""

    @field_validator("current_step", "expected_action", "reason")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


class TaskPauseRequest(BaseModel):
    """Payload for pausing a task."""

    reason: str = ""

    @field_validator("reason")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class TaskStateList(BaseModel):
    tasks: List[TaskState] = Field(default_factory=list)


class TaskStepSuggestion(BaseModel):
    """A proposal for the task state, derived from the dialogue.

    Produced by :class:`backend.tasks.extractor.TaskStepExtractor` in a single
    model call: the stage, the current step and the expected action all come
    from one answer. The manager decides what is actually stored, and the stage
    is still validated against the state machine.
    """

    stage: Optional[Stage] = None
    current_step: str = ""
    expected_action: str = ""
    confidence: float = 0.0
    source: str = "llm"

    @field_validator("current_step", "expected_action")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    def is_empty(self) -> bool:
        return not self.current_step and not self.expected_action and not self.stage