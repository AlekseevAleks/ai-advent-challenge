"""Memory endpoints — the three layers exposed to the UI.

Short-term and working memory are chat-scoped; long-term memory is global.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import get_memory_service
from backend.memory.models import (
    LongTermCreate,
    LongTermEntry,
    LongTermMemory,
    LongTermUpdate,
    MemoryAnalysisReport,
    MemoryOverview,
    ShortTermMemory,
    WorkingMemory,
    WorkingMemoryUpdate,
)
from backend.services.memory_service import MemoryService

router = APIRouter(prefix="/api", tags=["memory"])


# ------------------------------------------------------------------ overview
@router.get("/memory", response_model=MemoryOverview)
async def memory_overview(
    chat_id: Optional[str] = Query(default=None),
    service: MemoryService = Depends(get_memory_service),
) -> MemoryOverview:
    """All three layers at once, for the memory screen."""
    return service.get_overview(chat_id)


# --------------------------------------------------------------- short-term
@router.get("/chats/{chat_id}/memory/short-term", response_model=ShortTermMemory)
async def get_short_term_memory(
    chat_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> ShortTermMemory:
    """The current dialogue of a chat (trimmed to the context window)."""
    return service.get_short_term(chat_id)


# ------------------------------------------------------------------ working
@router.get("/chats/{chat_id}/memory/working", response_model=WorkingMemory)
async def get_working_memory(
    chat_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> WorkingMemory:
    """Structured state of the task of a chat."""
    return service.get_working(chat_id)


@router.put("/chats/{chat_id}/memory/working", response_model=WorkingMemory)
async def replace_working_memory(
    chat_id: str,
    payload: WorkingMemoryUpdate,
    service: MemoryService = Depends(get_memory_service),
) -> WorkingMemory:
    """Overwrite working memory (manual edit)."""
    return service.replace_working(chat_id, payload)


@router.delete("/chats/{chat_id}/memory/working", status_code=204)
async def clear_working_memory(
    chat_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> None:
    """Clear working memory of a chat."""
    service.clear_working(chat_id)


@router.post("/chats/{chat_id}/memory/analyze", response_model=MemoryAnalysisReport)
async def analyze_memory(
    chat_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryAnalysisReport:
    """Force a memory analysis of the last exchange of a chat."""
    return await service.analyze_last_exchange(chat_id)


# ---------------------------------------------------------------- long-term
@router.get("/memory/long-term", response_model=LongTermMemory)
async def get_long_term_memory(
    service: MemoryService = Depends(get_memory_service),
) -> LongTermMemory:
    """Durable facts about the user, shared across all chats."""
    return service.get_long_term()


@router.post("/memory/long-term", response_model=LongTermEntry, status_code=201)
async def create_long_term_memory(
    payload: LongTermCreate,
    service: MemoryService = Depends(get_memory_service),
) -> LongTermEntry:
    """Add a long-term fact manually."""
    return service.create_long_term(payload)


@router.put("/memory/long-term/{memory_id}", response_model=LongTermEntry)
async def update_long_term_memory(
    memory_id: str,
    payload: LongTermUpdate,
    service: MemoryService = Depends(get_memory_service),
) -> LongTermEntry:
    """Edit a long-term fact."""
    return service.update_long_term(memory_id, payload)


@router.delete("/memory/long-term/{memory_id}", status_code=204)
async def delete_long_term_memory(
    memory_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> None:
    """Forget a long-term fact."""
    service.delete_long_term(memory_id)