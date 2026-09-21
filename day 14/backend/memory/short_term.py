"""Short-term memory — the current conversation.

This layer is the ``messages`` table of one chat. It answers "what was said in
this dialogue?" and is the only layer that is scoped to a single chat and
trimmed to a context window before being sent to the model.
"""

from __future__ import annotations

from typing import List, Optional

from backend.database.repositories import MessageRepository
from backend.memory.models import (
    ShortTermEntry,
    ShortTermMemory as ShortTermMemoryModel,
)

#: How many trailing messages are handed to the model by default.
DEFAULT_MAX_MESSAGES = 40


class ShortTermMemory:
    """Read/write access to the dialogue of a single chat."""

    layer = "short-term"

    def __init__(
        self,
        messages: Optional[MessageRepository] = None,
        *,
        max_messages: int = DEFAULT_MAX_MESSAGES,
    ) -> None:
        self._messages = messages or MessageRepository()
        self.max_messages = max_messages

    def append(self, chat_id: str, role: str, content: str) -> ShortTermEntry:
        """Store one message of the current dialogue."""
        message = self._messages.add(chat_id, role, content)  # type: ignore[arg-type]
        return ShortTermEntry(
            id=message.id,
            chat_id=message.chat_id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
        )

    def get(
        self, chat_id: str, *, limit: Optional[int] = None
    ) -> ShortTermMemoryModel:
        """Return the dialogue, trimmed to the last ``limit`` messages."""
        effective_limit = limit if limit is not None else self.max_messages
        history = self._messages.list_for_chat(chat_id)
        total = len(history)
        truncated = False
        if effective_limit and total > effective_limit:
            history = history[-effective_limit:]
            truncated = True

        return ShortTermMemoryModel(
            chat_id=chat_id,
            entries=[
                ShortTermEntry(
                    id=message.id,
                    chat_id=message.chat_id,
                    role=message.role,
                    content=message.content,
                    created_at=message.created_at,
                )
                for message in history
            ],
            total_messages=total,
            truncated=truncated,
            max_messages=effective_limit,
        )

    def as_chat_messages(
        self, chat_id: str, *, limit: Optional[int] = None
    ) -> List[dict]:
        """Return the dialogue in OpenAI ``messages`` format."""
        memory = self.get(chat_id, limit=limit)
        return [
            {"role": entry.role, "content": entry.content} for entry in memory.entries
        ]

    def count(self, chat_id: str) -> int:
        return self._messages.count_for_chat(chat_id)

    def clear(self, chat_id: str) -> int:
        """Drop the whole dialogue of a chat (used when the chat is deleted)."""
        history = self._messages.list_for_chat(chat_id)
        removed = 0
        for message in history:
            if self._messages.delete(message.id):
                removed += 1
        return removed