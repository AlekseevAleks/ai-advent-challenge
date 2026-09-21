"""MemoryManager — the single entry point to all three memory layers.

Responsibilities:

* expose a uniform API over short-term / working / long-term memory;
* decide *what is actually persisted* after an extraction (the extractor only
  proposes);
* build the compact text context that is injected into the LLM prompt;
* emit ``[MEMORY]`` debug logs so the decision process is observable.

The manager never talks to the LLM itself — that is the extractor's job — and
never builds HTTP payloads — that is the chat service's job.
"""

from __future__ import annotations

from typing import List, Optional

from backend.memory.extractor import MemoryExtractor
from backend.memory.long_term import LongTermMemory
from backend.memory.models import (
    LongTermCandidate,
    LongTermEntry,
    LongTermMemory as LongTermMemoryModel,
    MemoryAnalysisReport,
    MemoryExtractionResult,
    MemoryOverview,
    ShortTermMemory as ShortTermMemoryModel,
    WorkingMemory as WorkingMemoryModel,
    WorkingMemoryData,
    WorkingMemoryPatch,
)
from backend.memory.short_term import ShortTermMemory
from backend.memory.working import WorkingMemory
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

#: How many long-term facts are injected into the prompt at most.
MAX_LONG_TERM_IN_PROMPT = 25


class MemoryManager:
    """Coordinates the three memory layers and the extraction pipeline."""

    def __init__(
        self,
        *,
        short_term: Optional[ShortTermMemory] = None,
        working: Optional[WorkingMemory] = None,
        long_term: Optional[LongTermMemory] = None,
        extractor: Optional[MemoryExtractor] = None,
    ) -> None:
        self.short_term = short_term or ShortTermMemory()
        self.working = working or WorkingMemory()
        self.long_term = long_term or LongTermMemory()
        self.extractor = extractor or MemoryExtractor()

    # ------------------------------------------------------------- read API
    def get_short_term_memory(
        self, chat_id: str, *, limit: Optional[int] = None
    ) -> ShortTermMemoryModel:
        return self.short_term.get(chat_id, limit=limit)

    def get_working_memory(self, chat_id: str) -> WorkingMemoryModel:
        return self.working.get(chat_id)

    def get_long_term_memory(self) -> LongTermMemoryModel:
        return self.long_term.get()

    def get_overview(self, chat_id: Optional[str] = None) -> MemoryOverview:
        """Everything the memory screen needs, in one call."""
        short_term = self.get_short_term_memory(chat_id) if chat_id else None
        working = self.get_working_memory(chat_id) if chat_id else None
        return MemoryOverview(
            chat_id=chat_id,
            short_term=short_term,
            working=working,
            long_term=self.get_long_term_memory(),
            prompt_preview=self.build_prompt_context(chat_id) if chat_id else "",
        )

    # ------------------------------------------------------------ write API
    def save_to_short_term(self, chat_id: str, role: str, content: str):
        """Append one message to the current dialogue."""
        entry = self.short_term.append(chat_id, role, content)
        logger.debug("[MEMORY] Short-term: сохранено сообщение %s (%s)", entry.id, role)
        return entry

    def save_to_working_memory(
        self, chat_id: str, patch: WorkingMemoryPatch
    ) -> tuple[WorkingMemoryData, List[str]]:
        """Merge a patch into the task state of a chat."""
        data, changes = self.working.apply_patch(chat_id, patch)
        if changes:
            logger.info("[MEMORY] Working memory update: %s", "; ".join(changes))
        return data, changes

    def replace_working_memory(
        self, chat_id: str, data: WorkingMemoryData
    ) -> WorkingMemoryModel:
        logger.info("[MEMORY] Working memory перезаписана вручную (чат %s)", chat_id)
        return self.working.replace(chat_id, data)

    def clear_working_memory(self, chat_id: str) -> bool:
        removed = self.working.clear(chat_id)
        logger.info("[MEMORY] Working memory очищена (чат %s)", chat_id)
        return removed

    def save_to_long_term(
        self,
        *,
        category: str,
        key: str,
        value: str,
        source: str = "manual",
        confidence: float = 1.0,
    ) -> LongTermEntry:
        entry = self.long_term.remember(
            category=category,  # type: ignore[arg-type]
            key=key,
            value=value,
            source=source,
            confidence=confidence,
        )
        logger.info(
            "[MEMORY] Long-term сохранено: %s.%s = %s", entry.category, entry.key, entry.value
        )
        return entry

    def forget_long_term(self, memory_id: str) -> bool:
        removed = self.long_term.forget(memory_id)
        if removed:
            logger.info("[MEMORY] Long-term удалено: %s", memory_id)
        return removed

    def update_long_term(self, memory_id: str, **fields) -> Optional[LongTermEntry]:
        entry = self.long_term.update(memory_id, **fields)
        if entry is not None:
            logger.info(
                "[MEMORY] Long-term обновлено: %s.%s = %s",
                entry.category,
                entry.key,
                entry.value,
            )
        return entry

    # ------------------------------------------------------------- lifecycle
    def on_chat_deleted(self, chat_id: str) -> None:
        """Drop chat-scoped layers, keep the user-level one.

        Short-term memory lives in ``messages`` and is removed by the chat
        repository (``ON DELETE CASCADE``); working memory is removed here.
        Long-term memory is intentionally untouched: it belongs to the user,
        not to the chat.
        """
        self.working.clear(chat_id)
        logger.info(
            "[MEMORY] Чат %s удалён: short-term и working очищены, long-term сохранена",
            chat_id,
        )

    # -------------------------------------------------------------- analysis
    async def analyze(
        self,
        chat_id: str,
        user_message: str,
        *,
        assistant_message: str = "",
        persist: bool = True,
    ) -> MemoryAnalysisReport:
        """Classify a message and (optionally) persist the accepted parts.

        This is the "explicit decision" step required by the assignment: the
        extractor proposes, the manager validates and decides.
        """
        logger.info("[MEMORY] Message analyzed (чат %s)", chat_id)

        working_context = self._format_working(self.working.get_data(chat_id))
        long_term_context = self._format_long_term(self.long_term.list())

        result: MemoryExtractionResult = await self.extractor.extract(
            user_message,
            assistant_message=assistant_message,
            working_memory_context=working_context,
            long_term_context=long_term_context,
        )

        logger.info("[MEMORY] Short-term: %s", "yes" if result.short_term else "no")

        report = MemoryAnalysisReport(
            chat_id=chat_id,
            short_term_saved=result.short_term,
            summary=result.summary,
            source=result.source,
        )

        if not persist:
            report.long_term_rejected = list(result.long_term_candidates)
            return report

        if result.working_memory is not None and not result.working_memory.is_empty():
            _, changes = self.save_to_working_memory(chat_id, result.working_memory)
            report.working_memory_updated = bool(changes)
            report.working_memory_changes = changes

        for candidate in result.long_term_candidates:
            logger.info(
                "[MEMORY] Long-term candidate: %s = %s (confidence %.2f)",
                candidate.key,
                candidate.value,
                candidate.confidence,
            )

        accepted, rejected = self.long_term.accept_candidates(
            result.long_term_candidates, source=result.source
        )
        report.long_term_accepted = accepted
        report.long_term_rejected = rejected

        for entry in accepted:
            logger.info(
                "[MEMORY] Long-term candidate accepted: %s = %s", entry.key, entry.value
            )
        for candidate in rejected:
            logger.info(
                "[MEMORY] Long-term candidate rejected: %s = %s (%s)",
                candidate.key,
                candidate.value,
                candidate.reason,
            )

        return report

    # ---------------------------------------------------------- prompt builder
    def build_prompt_context(self, chat_id: str) -> str:
        """Compact text context assembled from all three layers.

        The order mirrors the assignment: long-term → working → short-term.
        Raw JSON is never sent to the model.
        """
        sections: List[str] = []

        long_term = self._format_long_term(self.long_term.list())
        if long_term:
            sections.append(f"## Long-term memory\n\n{long_term}")

        working = self._format_working(self.working.get_data(chat_id))
        if working:
            sections.append(f"## Working memory\n\n{working}")

        return "\n\n".join(sections)

    def build_messages(
        self,
        chat_id: str,
        user_message: str,
        *,
        system_prompt: Optional[str] = None,
        history_limit: Optional[int] = None,
    ) -> List[dict]:
        """Build the full OpenAI ``messages`` array for one request.

        Layout: system prompt → long-term → working → short-term → user message.
        """
        messages: List[dict] = []

        base_system = system_prompt or (
            "Ты — полезный ассистент в локальном AI-чате. "
            "Учитывай память агента: долговременные факты о пользователе, "
            "состояние текущей задачи и историю диалога."
        )
        context = self.build_prompt_context(chat_id)
        if context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"{base_system}\n\n"
                        "Ниже — память агента. Используй её, но не пересказывай "
                        "пользователю без необходимости.\n\n"
                        f"{context}"
                    ),
                }
            )
        else:
            messages.append({"role": "system", "content": base_system})

        messages.extend(
            self.short_term.as_chat_messages(chat_id, limit=history_limit)
        )
        return messages

    # ------------------------------------------------------------- formatting
    @staticmethod
    def _format_long_term(entries: List[LongTermEntry]) -> str:
        if not entries:
            return ""
        lines: List[str] = []
        by_category: dict = {}
        for entry in entries[:MAX_LONG_TERM_IN_PROMPT]:
            by_category.setdefault(entry.category, []).append(entry)

        titles = {
            "preference": "User preferences",
            "decision": "Standing decisions",
            "constraint": "Standing constraints",
            "fact": "Known facts",
        }
        for category, items in by_category.items():
            lines.append(f"{titles.get(category, category)}:")
            for entry in items:
                lines.append(f"- {entry.value}")
        return "\n".join(lines)

    @staticmethod
    def _format_working(data: WorkingMemoryData) -> str:
        if data.is_empty():
            return ""
        lines: List[str] = []
        if data.task:
            lines.append(f"Current task:\n{data.task}")
        if data.goal:
            lines.append(f"Goal:\n{data.goal}")
        if data.stack:
            lines.append(f"Stack:\n{', '.join(data.stack)}")
        if data.current_step:
            lines.append(f"Current step:\n{data.current_step}")
        if data.completed:
            lines.append("Completed:\n" + "\n".join(f"- {item}" for item in data.completed))
        if data.constraints:
            lines.append(
                "Constraints:\n" + "\n".join(f"- {item}" for item in data.constraints)
            )
        if data.decisions:
            lines.append(
                "Decisions:\n" + "\n".join(f"- {item}" for item in data.decisions)
            )
        return "\n\n".join(lines)