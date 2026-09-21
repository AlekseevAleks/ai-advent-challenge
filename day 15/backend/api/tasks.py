"""Task state endpoints.

The task state is a finite state machine. Every move goes through
``TransitionManager``, which loads the rules the user configured on the
*Task State Rules* page, so an invalid move such as ``planning → done`` is
rejected with 409 and the stage is left untouched.

Two transition endpoints exist on purpose:

* ``POST /{task_id}/transition`` — the original one, returning the new
  ``TaskState`` and raising 409 when the move is refused;
* ``POST /{task_id}/transition/check`` — the rule-based one, returning a
  ``TransitionOutcome`` that describes the refusal instead of raising, so the
  UI can show *why* a move is unavailable.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import get_memory_service
from backend.invariants.models import Invariant, InvariantCreate, InvariantList
from backend.services.memory_service import MemoryService
from backend.tasks.models import (
    TaskPauseRequest,
    TaskState,
    TaskStateCreate,
    TaskStateUpdate,
    TaskTransitionRequest,
)
from backend.tasks.manager import InvalidTransitionError
from backend.transitions.models import (
    AvailableTransitions,
    TaskFacts,
    TaskFactsUpdate,
    TransitionHistoryList,
    TransitionOutcome,
    TransitionRequest,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# ------------------------------------------------------- transitions (rules)
@router.get(
    "/{task_id}/available-transitions", response_model=AvailableTransitions
)
async def available_transitions(
    task_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> AvailableTransitions:
    """Every move configured from the current stage, with its verdict."""
    return service.available_transitions(task_id)



@router.post("/{task_id}/transition", response_model=TaskState)
async def transition_task(
    task_id: str,
    payload: TaskTransitionRequest,
    service: MemoryService = Depends(get_memory_service),
) -> TaskState:
    """Move the task to another stage, validating the edge.

    The move goes through ``TransitionManager``, so it obeys the rules
    configured on the *Task State Rules* page; a refused move is reported as
    409 with the reason.
    """
    outcome = service.transition_task_to(
        task_id,
        payload.stage,
        reason=payload.reason,
        trigger="user",
        current_step=payload.current_step,
        expected_action=payload.expected_action,
    )
    if not outcome.allowed:
        # The original error code is kept: callers already handle it.
        raise InvalidTransitionError(outcome.reason)
    return service.get_task_state(task_id)


@router.post("/{task_id}/transitions/apply", response_model=TransitionOutcome)
async def check_transition(
    task_id: str,
    payload: TransitionRequest,
    service: MemoryService = Depends(get_memory_service),
) -> TransitionOutcome:
    """Move a task, or refuse and explain why.

    A refusal is returned as a normal payload with ``allowed=false``: the stage
    is left untouched and the reason is reported to the caller.
    """
    return service.transition_task_to(
        task_id,
        payload.to_state,
        reason=payload.reason,
        trigger=payload.trigger,
        current_step=payload.current_step,
        expected_action=payload.expected_action,
    )


@router.get(
    "/{task_id}/transition-history", response_model=TransitionHistoryList
)
async def transition_history(
    task_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    service: MemoryService = Depends(get_memory_service),
) -> TransitionHistoryList:
    """Every transition attempt of a task, accepted or rejected."""
    return TransitionHistoryList(
        task_id=task_id, entries=service.transition_history(task_id, limit=limit)
    )


@router.get("/{task_id}/facts", response_model=TaskFacts)
async def get_task_facts(
    task_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> TaskFacts:
    """The facts transition conditions are checked against.

    ``missing`` lists the fields the active rules read but the task does not
    carry: a condition on such a field can never hold, so the user has to be
    told which fact to set.
    """
    return service.task_facts(task_id)


@router.put("/{task_id}/facts", response_model=TaskFacts)
async def set_task_facts(
    task_id: str,
    payload: TaskFactsUpdate,
    service: MemoryService = Depends(get_memory_service),
) -> TaskFacts:
    """Set the task's own facts. An empty value clears the fact."""
    return service.set_task_facts(task_id, payload.facts)


@router.get("/{task_id}/transition-prompt-block")
async def transition_prompt_block(
    task_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> dict:
    """The exact lifecycle text injected into the system prompt."""
    return {"task_id": task_id, "block": service.transition_prompt_block(task_id)}


# ------------------------------------------------------------- task state
@router.get("/{task_id}/state", response_model=TaskState)
async def get_task_state(
    task_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> TaskState:
    """Current state of a task (``exists=False`` when it was never created)."""
    return service.get_task_state(task_id)


@router.post("/{task_id}/state", response_model=TaskState, status_code=201)
async def create_task_state(
    task_id: str,
    payload: Optional[TaskStateCreate] = None,
    service: MemoryService = Depends(get_memory_service),
) -> TaskState:
    """Create a task state. Existing states are returned untouched."""
    return service.create_task_state(task_id, payload)


@router.put("/{task_id}/state", response_model=TaskState)
async def update_task_state(
    task_id: str,
    payload: TaskStateUpdate,
    service: MemoryService = Depends(get_memory_service),
) -> TaskState:
    """Update the step and expected action without changing stage or status."""
    return service.update_task_state(task_id, payload)


@router.post("/{task_id}/pause", response_model=TaskState)
async def pause_task(
    task_id: str,
    payload: Optional[TaskPauseRequest] = None,
    service: MemoryService = Depends(get_memory_service),
) -> TaskState:
    """Pause the task, keeping its stage, step and expected action."""
    return service.pause_task(task_id, payload)


@router.post("/{task_id}/resume", response_model=TaskState)
async def resume_task(
    task_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> TaskState:
    """Resume a paused task at the stage and step it was paused at."""
    return service.resume_task(task_id)


@router.post("/{task_id}/complete", response_model=TaskState)
async def complete_task(
    task_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> TaskState:
    """Finish the task, walking the remaining stages in order."""
    return service.complete_task(task_id)


@router.post("/{task_id}/refresh-step", response_model=TaskState)
async def refresh_task_step(
    task_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> TaskState:
    """Recompute ``current_step`` and ``expected_action`` from the dialogue.

    The same computation runs automatically in the background after every
    assistant reply; this endpoint forces it on demand.
    """
    state = await service.refresh_task_step(task_id)
    if state is None:
        # Nothing usable was derived: return the unchanged state so the UI can
        # simply re-render instead of treating it as an error.
        return service.get_task_state(task_id)
    return state


@router.get("/{task_id}/invariants", response_model=InvariantList)
async def list_task_invariants(
    task_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> InvariantList:
    """Invariants that apply to this task: its own plus the global ones."""
    return service.list_active_invariants(task_id)


@router.post("/{task_id}/invariants", response_model=Invariant, status_code=201)
async def create_task_invariant(
    task_id: str,
    payload: InvariantCreate,
    service: MemoryService = Depends(get_memory_service),
) -> Invariant:
    """Create an invariant scoped to this task."""
    payload.scope = "task"
    payload.task_id = task_id
    return service.create_invariant(payload)


@router.get("/{task_id}/prompt-block")
async def task_prompt_block(
    task_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> dict:
    """The exact task-state text injected into the system prompt."""
    return {"task_id": task_id, "block": service.task_prompt_block(task_id)}
