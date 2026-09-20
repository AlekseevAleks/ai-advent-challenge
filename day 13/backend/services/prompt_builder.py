"""PromptBuilder — assembles the full context for one LLM request.

The order is fixed and mirrors the assignment:

```
System instructions
+ User Profile        (how to answer)
+ Long-term Memory    (what to remember about the user)
+ Working Memory      (context of the current task)
+ Task State          (formalised stage / step / expected action)
+ Short-term Memory   (the current dialogue)
+ Current user message
```

The builder owns no storage: it asks the profile manager, the memory manager
and the task manager for their compact text blocks and concatenates them. That
keeps the sources independent — each can change without touching the others.
"""

from __future__ import annotations

from typing import List, Optional

from backend.memory.manager import MemoryManager
from backend.profile.manager import ProfileManager
from backend.tasks.manager import TaskStateManager
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "Ты — полезный ассистент в локальном AI-чате. "
    "Следуй профилю пользователя, учитывай память агента и историю диалога."
)

#: Explains to the model how to treat the blocks that follow.
CONTEXT_PREAMBLE = (
    "Ниже — профиль пользователя, память агента и состояние задачи. "
    "Профиль определяет, КАК отвечать (язык, стиль, формат, уровень) — "
    "соблюдай его в каждом ответе. Память описывает, ЧТО известно. "
    "TASK STATE описывает, ГДЕ находится задача: продолжай с указанного шага "
    "и не предлагай заново то, что уже сделано. "
    "Не пересказывай эти блоки пользователю без необходимости."
)


class PromptBuilder:
    """Builds the ``messages`` array sent to the model."""

    def __init__(
        self,
        *,
        memory: MemoryManager,
        profile: ProfileManager,
        tasks: Optional[TaskStateManager] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        self.memory = memory
        self.profile = profile
        self.tasks = tasks
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    # ------------------------------------------------------------- sections
    def build_system_content(self, chat_id: str, profile_id: Optional[str] = None) -> str:
        """System message: instructions + profile + long-term + working memory.

        Without an explicit ``profile_id`` the *active* profile is used, so a
        profile switch applies to the very next request.
        """
        sections: List[str] = [self.system_prompt]

        profile_block = self.profile.build_prompt_block(profile_id)
        memory_block = self.memory.build_prompt_context(chat_id)
        task_block = self.tasks.build_prompt_block(chat_id) if self.tasks else ""

        if profile_block or memory_block or task_block:
            sections.append(CONTEXT_PREAMBLE)
        if profile_block:
            sections.append(profile_block)
        if memory_block:
            sections.append(memory_block)
        if task_block:
            sections.append(task_block)

        return "\n\n".join(sections)

    def build_messages(
        self,
        chat_id: str,
        *,
        profile_id: Optional[str] = None,
        history_limit: Optional[int] = None,
    ) -> List[dict]:
        """Full request context, ready to be sent to the API."""
        messages: List[dict] = [
            {
                "role": "system",
                "content": self.build_system_content(chat_id, profile_id),
            }
        ]
        messages.extend(
            self.memory.short_term.as_chat_messages(chat_id, limit=history_limit)
        )
        return messages

    # -------------------------------------------------------------- preview
    def preview(self, chat_id: str, profile_id: Optional[str] = None) -> str:
        """Human-readable preview of the context, for the UI and logs."""
        parts = [self.build_system_content(chat_id, profile_id)]
        history = self.memory.short_term.get(chat_id)
        if history.entries:
            lines = [
                f"{entry.role}: {entry.content[:200]}" for entry in history.entries
            ]
            parts.append("## Current conversation\n\n" + "\n".join(lines))
        return "\n\n".join(part for part in parts if part)

    def log_request(self, chat_id: str, profile_id: Optional[str] = None) -> None:
        """Log which sources contributed to the request."""
        resolved = profile_id or self.profile.get_active_profile_id()
        profile_block = self.profile.build_prompt_block(resolved)
        memory_block = self.memory.build_prompt_context(chat_id)
        task_block = self.tasks.build_prompt_block(chat_id) if self.tasks else ""
        logger.info(
            "[PROMPT] chat=%s active_profile=%s | profile=%s memory=%s task=%s",
            chat_id,
            self.profile.describe(resolved),
            "yes" if profile_block else "no",
            "yes" if memory_block else "no",
            "yes" if task_block else "no",
        )