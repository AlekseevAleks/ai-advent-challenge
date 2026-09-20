"""Long-term memory — durable facts about the user.

This is the only layer that survives a chat: it is scoped to the *user*, not to
a conversation, and it is what a brand-new chat can still see. Because of that
it is guarded by strict acceptance rules (see :mod:`backend.memory.manager`).
"""

from __future__ import annotations

from typing import List, Optional

from backend.database.memory_repositories import LongTermMemoryRepository
from backend.memory.models import (
    LongTermCandidate,
    LongTermEntry,
    LongTermMemory as LongTermMemoryModel,
    MemoryCategory,
)

#: A candidate must reach this confidence to be stored automatically.
DEFAULT_MIN_CONFIDENCE = 0.6

#: Keys that are too generic to be useful as durable user facts.
_BANNED_KEYS = {
    "question",
    "message",
    "text",
    "content",
    "chat",
    "conversation",
    "task",
    "current_task",
    "current_step",
    "todo",
    "temporary",
}

#: Values that carry no durable information.
_BANNED_VALUES = {
    "",
    "n/a",
    "none",
    "null",
    "unknown",
    "неизвестно",
    "нет",
    "да",
    "yes",
    "no",
}


class LongTermMemory:
    """Durable user profile and project-wide decisions."""

    layer = "long-term"

    def __init__(
        self,
        repository: Optional[LongTermMemoryRepository] = None,
        *,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> None:
        self._repo = repository or LongTermMemoryRepository()
        self.min_confidence = min_confidence

    # ------------------------------------------------------------------ read
    def get(self) -> LongTermMemoryModel:
        return LongTermMemoryModel(entries=self._repo.list())

    def list(self) -> List[LongTermEntry]:
        return self._repo.list()

    def get_entry(self, memory_id: str) -> Optional[LongTermEntry]:
        return self._repo.get(memory_id)

    # ----------------------------------------------------------------- write
    def remember(
        self,
        *,
        category: MemoryCategory,
        key: str,
        value: str,
        source: str = "manual",
        confidence: float = 1.0,
    ) -> LongTermEntry:
        """Store a fact, updating the value if the (category, key) already exists."""
        return self._repo.upsert(
            category=category,
            key=key.strip(),
            value=value.strip(),
            source=source,
            confidence=confidence,
        )

    def update(self, memory_id: str, **fields) -> Optional[LongTermEntry]:
        return self._repo.update(memory_id, **fields)

    def forget(self, memory_id: str) -> bool:
        return self._repo.delete(memory_id)

    def clear(self) -> int:
        return self._repo.clear()

    # ------------------------------------------------------------ validation
    def validate_candidate(self, candidate: LongTermCandidate) -> Optional[str]:
        """Return a rejection reason, or ``None`` if the candidate is acceptable.

        The LLM proposes; this method disposes. It encodes the rules from the
        assignment: only durable, user-level, non-temporary information may be
        promoted to long-term memory.
        """
        key = (candidate.key or "").strip().lower()
        value = (candidate.value or "").strip()

        if not key or not value:
            return "пустой ключ или значение"
        if key in _BANNED_KEYS:
            return f"ключ '{key}' относится к текущей задаче, а не к пользователю"
        if value.lower() in _BANNED_VALUES:
            return "значение не несёт устойчивой информации"
        if len(value) > 500:
            return "значение слишком длинное для долговременного факта"
        if candidate.confidence < self.min_confidence:
            return (
                f"низкая уверенность ({candidate.confidence:.2f} < "
                f"{self.min_confidence:.2f})"
            )
        return None

    def accept_candidates(
        self, candidates: List[LongTermCandidate], *, source: str = "llm"
    ) -> tuple[List[LongTermEntry], List[LongTermCandidate]]:
        """Split candidates into accepted entries and rejected ones."""
        accepted: List[LongTermEntry] = []
        rejected: List[LongTermCandidate] = []
        for candidate in candidates:
            reason = self.validate_candidate(candidate)
            if reason is not None:
                candidate.reason = reason
                rejected.append(candidate)
                continue
            accepted.append(
                self.remember(
                    category=candidate.category,
                    key=candidate.key,
                    value=candidate.value,
                    source=source,
                    confidence=candidate.confidence,
                )
            )
        return accepted, rejected