"""Task lifecycle endpoints: states, transition rules and transitions.

The lifecycle is configuration, not code: the user defines the states and the
rules between them on the *Task State Rules* page, and the backend loads them
from the database on every transition. That is what makes a rule edited in the
UI apply to the very next request without a restart.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import get_memory_service
from backend.services.memory_service import MemoryService
from backend.transitions.models import (
    TaskStateDefinition,
    TaskStateDefinitionCreate,
    TaskStateDefinitionList,
    TaskStateDefinitionUpdate,
    TransitionRule,
    TransitionRuleCreate,
    TransitionRuleList,
    TransitionRuleUpdate,
)

router = APIRouter(prefix="/api", tags=["transitions"])


# ------------------------------------------------------------------- states
@router.get("/task-states", response_model=TaskStateDefinitionList)
async def list_task_states(
    service: MemoryService = Depends(get_memory_service),
) -> TaskStateDefinitionList:
    """Every configured state, plus which one is initial and which are final."""
    return service.list_task_states()


@router.post("/task-states", response_model=TaskStateDefinition, status_code=201)
async def create_task_state(
    payload: TaskStateDefinitionCreate,
    service: MemoryService = Depends(get_memory_service),
) -> TaskStateDefinition:
    """Create a state. The first state created becomes the initial one."""
    return service.create_task_state_definition(payload)


@router.get("/task-states/{state_id}", response_model=TaskStateDefinition)
async def get_task_state(
    state_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> TaskStateDefinition:
    return service.get_task_state_definition(state_id)


@router.put("/task-states/{state_id}", response_model=TaskStateDefinition)
async def update_task_state(
    state_id: str,
    payload: TaskStateDefinitionUpdate,
    service: MemoryService = Depends(get_memory_service),
) -> TaskStateDefinition:
    """Rename, describe, activate or deactivate a state."""
    return service.update_task_state_definition(state_id, payload)


@router.delete("/task-states/{state_id}", status_code=204)
async def delete_task_state(
    state_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> None:
    """Delete a state. Refused with 409 while rules still reference it."""
    service.delete_task_state_definition(state_id)


# -------------------------------------------------------------------- rules
@router.get("/transition-rules", response_model=TransitionRuleList)
async def list_transition_rules(
    active_only: bool = Query(default=False),
    service: MemoryService = Depends(get_memory_service),
) -> TransitionRuleList:
    """Every configured transition rule."""
    return TransitionRuleList(
        rules=service.list_transition_rules(active_only=active_only)
    )


@router.post("/transition-rules", response_model=TransitionRule, status_code=201)
async def create_transition_rule(
    payload: TransitionRuleCreate,
    service: MemoryService = Depends(get_memory_service),
) -> TransitionRule:
    """Create a rule. Both states must exist and the edge must be unique."""
    return service.create_transition_rule(payload)


@router.get("/transition-rules/{rule_id}", response_model=TransitionRule)
async def get_transition_rule(
    rule_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> TransitionRule:
    return service.get_transition_rule(rule_id)


@router.put("/transition-rules/{rule_id}", response_model=TransitionRule)
async def update_transition_rule(
    rule_id: str,
    payload: TransitionRuleUpdate,
    service: MemoryService = Depends(get_memory_service),
) -> TransitionRule:
    """Update a rule. The change applies to the next transition."""
    return service.update_transition_rule(rule_id, payload)


@router.delete("/transition-rules/{rule_id}", status_code=204)
async def delete_transition_rule(
    rule_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> None:
    service.delete_transition_rule(rule_id)


@router.post("/transition-rules/{rule_id}/activate", response_model=TransitionRule)
async def activate_transition_rule(
    rule_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> TransitionRule:
    """Make the rule binding again."""
    return service.activate_transition_rule(rule_id)


@router.post(
    "/transition-rules/{rule_id}/deactivate", response_model=TransitionRule
)
async def deactivate_transition_rule(
    rule_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> TransitionRule:
    """Stop allowing the move without deleting the rule."""
    return service.deactivate_transition_rule(rule_id)


@router.post("/transition-rules/{rule_id}/check")
async def check_transition_rule(
    rule_id: str,
    payload: Optional[dict] = None,
    service: MemoryService = Depends(get_memory_service),
) -> dict:
    """Evaluate a rule against the given facts (or an empty set)."""
    facts = (payload or {}).get("facts") or {}
    return service.check_transition_rule(rule_id, facts)


# -------------------------------------------------------------- transitions
# The task-scoped transition endpoints live in ``backend.api.tasks``: they are
# declared there so the rule-based ``POST /api/tasks/{id}/transition`` is
# registered before the legacy payload shape and is not shadowed by it.
