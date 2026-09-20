"""Working memory — the state of the task the agent is working on.

Unlike short-term memory this is *structured*: a task, a stack, a current step,
completed items, constraints and decisions. It belongs to one chat, but it is
not a transcript — it is the distilled state of the work in progress.
"""

from __future__ import annotations

from typing import List, Optional

from backend.database.memory_repositories import WorkingMemoryRepository
from backend.memory.models import (
    WorkingMemory as WorkingMemoryModel,
    WorkingMemoryData,
    WorkingMemoryPatch,
)

#: Fields that hold lists and are merged (union) instead of overwritten.
_LIST_FIELDS = ("stack", "completed", "constraints", "decisions")
#: Fields that hold a single value and are overwritten when a patch provides one.
_SCALAR_FIELDS = ("task", "goal", "current_step")


class WorkingMemory:
    """Structured task state, one record per chat."""

    layer = "working"

    def __init__(self, repository: Optional[WorkingMemoryRepository] = None) -> None:
        self._repo = repository or WorkingMemoryRepository()

    def get(self, chat_id: str) -> WorkingMemoryModel:
        data = self._repo.get(chat_id)
        if data is None:
            return WorkingMemoryModel(chat_id=chat_id, exists=False)
        return WorkingMemoryModel(
            chat_id=chat_id,
            data=data,
            updated_at=self._repo.get_updated_at(chat_id),
            exists=True,
        )

    def get_data(self, chat_id: str) -> WorkingMemoryData:
        return self._repo.get(chat_id) or WorkingMemoryData()

    def replace(self, chat_id: str, data: WorkingMemoryData) -> WorkingMemoryModel:
        """Overwrite the whole working memory (manual edit from the UI)."""
        updated_at = self._repo.save(chat_id, data)
        return WorkingMemoryModel(
            chat_id=chat_id, data=data, updated_at=updated_at, exists=True
        )

    def apply_patch(
        self, chat_id: str, patch: WorkingMemoryPatch
    ) -> tuple[WorkingMemoryData, List[str]]:
        """Merge a patch into the stored state.

        Returns the new state and a human-readable list of what changed, so the
        caller can log and display exactly which fields were updated.
        """
        current = self.get_data(chat_id)
        changes: List[str] = []

        for field in _SCALAR_FIELDS:
            new_value = getattr(patch, field)
            if not new_value:
                continue
            new_value = new_value.strip()
            if not new_value or new_value == getattr(current, field):
                continue
            setattr(current, field, new_value)
            changes.append(f"{field} = {new_value}")

        for field in _LIST_FIELDS:
            incoming = getattr(patch, field) or []
            existing: List[str] = list(getattr(current, field))
            added = [
                item.strip()
                for item in incoming
                if item and item.strip() and item.strip() not in existing
            ]
            if not added:
                continue
            setattr(current, field, existing + added)
            changes.append(f"{field} += {', '.join(added)}")

        if changes:
            self._repo.save(chat_id, current)
        return current, changes

    def clear(self, chat_id: str) -> bool:
        return self._repo.delete(chat_id)