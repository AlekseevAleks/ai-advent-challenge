"""Invariant endpoints.

Invariants are mandatory constraints, stored separately from memory and task
state. The backend validates every conflict check, so a rule the model invented
is never reported to the user.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import get_memory_service
from backend.invariants.models import (
    ConflictCheckResult,
    Invariant,
    InvariantCreate,
    InvariantList,
    InvariantUpdate,
)
from backend.services.memory_service import MemoryService
from backend.utils.errors import NotFoundError

router = APIRouter(prefix="/api/invariants", tags=["invariants"])


# --------------------------------------------------------------- collection
@router.get("", response_model=InvariantList)
async def list_invariants(
    scope: Optional[str] = Query(default=None),
    task_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    service: MemoryService = Depends(get_memory_service),
) -> InvariantList:
    """All invariants, optionally filtered by scope, task or status."""
    return service.list_invariants(scope=scope, task_id=task_id, status=status)


@router.post("", response_model=Invariant, status_code=201)
async def create_invariant(
    payload: InvariantCreate,
    service: MemoryService = Depends(get_memory_service),
) -> Invariant:
    """Create an invariant. Task-scoped rules require a ``task_id``."""
    return service.create_invariant(payload)


@router.post("/check", response_model=ConflictCheckResult)
async def check_invariants(
    payload: dict,
    task_id: Optional[str] = Query(default=None),
    service: MemoryService = Depends(get_memory_service),
) -> ConflictCheckResult:
    """Check a request against the active invariants.

    Returns the conflicts found, a compatible alternative when one exists, and
    whether the user explicitly asked to change a rule.
    """
    request = str(payload.get("request") or "").strip()
    if not request:
        raise NotFoundError("Укажите поле 'request' с текстом запроса.")
    return await service.check_invariants(request, task_id=task_id)


# ------------------------------------------------------------------- single
@router.get("/{invariant_id}", response_model=Invariant)
async def get_invariant(
    invariant_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> Invariant:
    invariant = service.get_invariant(invariant_id)
    if not invariant.exists:
        raise NotFoundError("Инвариант не найден.")
    return invariant


@router.put("/{invariant_id}", response_model=Invariant)
async def update_invariant(
    invariant_id: str,
    payload: InvariantUpdate,
    service: MemoryService = Depends(get_memory_service),
) -> Invariant:
    """Update an invariant. Only the provided fields change."""
    return service.update_invariant(invariant_id, payload)


@router.delete("/{invariant_id}", status_code=204)
async def delete_invariant(
    invariant_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> None:
    service.delete_invariant(invariant_id)


@router.post("/{invariant_id}/activate", response_model=Invariant)
async def activate_invariant(
    invariant_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> Invariant:
    """Make the rule binding again."""
    return service.activate_invariant(invariant_id)


@router.post("/{invariant_id}/deactivate", response_model=Invariant)
async def deactivate_invariant(
    invariant_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> Invariant:
    """Stop enforcing the rule without deleting it."""
    return service.deactivate_invariant(invariant_id)
