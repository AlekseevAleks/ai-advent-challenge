"""Task state endpoints.

The task state is a finite state machine; the backend validates every
transition, so an invalid move such as ``planning → done`` is rejected with 409.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_memory_service
from backend.services.memory_service import MemoryService
from backend.tasks.models import (
    TaskPauseRequest,
    TaskState,
    TaskStateCreate,
    TaskStateUpdate,
    TaskTransitionRequest,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


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


@router.post("/{task_id}/transition", response_model=TaskState)
async def transition_task(
    task_id: str,
    payload: TaskTransitionRequest,
    service: MemoryService = Depends(get_memory_service),
) -> TaskState:
    """Move the task to another stage, validating the edge."""
    return service.transition_task(task_id, payload)


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


@router.get("/{task_id}/prompt-block")
async def task_prompt_block(
    task_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> dict:
    """The exact task-state text injected into the system prompt."""
    return {"task_id": task_id, "block": service.task_prompt_block(task_id)}