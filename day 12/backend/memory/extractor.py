"""Memory extraction — deciding *what kind of information* a message carries.

The extractor is deliberately side-effect free: it analyses a message and
returns a :class:`MemoryExtractionResult`. It never touches the database. The
:class:`~backend.memory.manager.MemoryManager` is the component that decides
what is actually persisted.

Two strategies are available:

* ``llm``    — ask the configured model to classify the message (default);
* ``rules``  — a deterministic heuristic fallback used when the API is not
  configured or the model returns something unusable.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from backend.memory.models import (
    LongTermCandidate,
    MemoryExtractionResult,
    WorkingMemoryPatch,
)
from backend.services.ai_client import AIClient
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

EXTRACTION_SYSTEM_PROMPT = """\
Ты — компонент Memory Extractor в приложении AI-чата.
Твоя задача — проанализировать сообщение пользователя и решить, какую
информацию из него стоит сохранить, и в какой слой памяти.

Слои памяти:
1. short_term  — обычный ход диалога. Сюда попадает всё, что относится только
   к текущему разговору (вопросы, уточнения, просьбы).
2. working     — структурированное состояние ТЕКУЩЕЙ задачи: цель, стек,
   текущий этап, выполненные пункты, ограничения, принятые в рамках задачи
   решения. Это НЕ факты о пользователе.
3. long_term   — устойчивая информация о ПОЛЬЗОВАТЕЛЕ или его постоянные
   предпочтения и решения, которые пригодятся в будущих, ещё не начатых чатах.

Правила для long_term (соблюдай строго):
- сохраняй только устойчивые предпочтения и постоянные решения;
- НЕ сохраняй разовые вопросы, временные детали, содержимое текущей задачи;
- НЕ сохраняй сам диалог;
- если сомневаешься — не сохраняй и поставь низкую confidence.

Верни СТРОГО JSON без пояснений и без markdown:
{
  "short_term": true,
  "working_memory": {
    "task": "..." | null,
    "goal": "..." | null,
    "stack": ["..."],
    "current_step": "..." | null,
    "completed": ["..."],
    "constraints": ["..."],
    "decisions": ["..."]
  },
  "long_term_memory": [
    {"category": "preference|decision|fact|constraint",
     "key": "snake_case_key",
     "value": "значение",
     "confidence": 0.0-1.0}
  ],
  "summary": "одна короткая строка о том, что извлечено"
}

Заполняй только те поля working_memory, которые действительно следуют из
сообщения. Если сообщение не содержит информации о задаче — верни null.
Если нет кандидатов в long_term — верни пустой массив.
"""

# ------------------------------------------------------------------ heuristics
_PREFERENCE_PATTERNS = (
    re.compile(
        r"\b(?:я\s+)?(?:предпочитаю|предпочитает|люблю|обычно\s+использую|"
        r"всегда\s+использую|мой\s+стек|я\s+работаю\s+с)\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:i\s+prefer|i\s+usually\s+use|i\s+always\s+use)\s+(.+)", re.IGNORECASE),
)

_TASK_PATTERNS = (
    re.compile(
        r"\b(?:сейчас\s+мы\s+разрабатываем|наша\s+задача|текущая\s+задача|"
        r"мы\s+делаем|мы\s+разрабатываем|цель\s*[:\-])\s*(.+)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:our\s+task|current\s+task|we\s+are\s+building)\s*[:\-]?\s*(.+)", re.IGNORECASE),
)

_STEP_PATTERNS = (
    re.compile(
        r"\b(?:давай\s+(?:теперь\s+)?(?:сделаем|сделай|реализуем|добавим)|"
        r"теперь\s+(?:сделаем|делаем|займёмся)|перейдём\s+к)\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:let'?s\s+(?:now\s+)?(?:do|build|implement|add))\s+(.+)", re.IGNORECASE),
)

_DECISION_PATTERNS = (
    re.compile(
        r"\b(?:давай\s+использовать|будем\s+использовать|используем|"
        r"решили\s+использовать|выбрали)\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:let'?s\s+use|we\s+will\s+use|we\s+decided\s+to\s+use)\s+(.+)", re.IGNORECASE),
)

_CONSTRAINT_PATTERNS = (
    re.compile(
        r"\b(?:обязательно|нужно\s+использовать|требуется|ограничение\s*[:\-]|"
        r"нельзя\s+использовать)\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:must\s+use|required\s+to|constraint\s*[:\-])\s+(.+)", re.IGNORECASE),
)

#: Known technologies, used to turn "предпочитаю Python и FastAPI" into two facts.
_KNOWN_TECH = (
    "python", "fastapi", "django", "flask", "postgresql", "postgres", "mysql",
    "sqlite", "mongodb", "redis", "react", "vue", "angular", "svelte",
    "typescript", "javascript", "node", "nodejs", "go", "golang", "rust",
    "java", "kotlin", "swift", "c#", "c++", "php", "laravel", "sqlalchemy",
    "docker", "kubernetes", "graphql", "rest", "jwt", "tailwind", "vite",
)

_TECH_KEY_HINTS = {
    "python": "preferred_language",
    "typescript": "preferred_language",
    "javascript": "preferred_language",
    "go": "preferred_language",
    "golang": "preferred_language",
    "rust": "preferred_language",
    "java": "preferred_language",
    "fastapi": "preferred_framework",
    "django": "preferred_framework",
    "flask": "preferred_framework",
    "react": "preferred_frontend",
    "vue": "preferred_frontend",
    "angular": "preferred_frontend",
    "svelte": "preferred_frontend",
    "postgresql": "preferred_database",
    "postgres": "preferred_database",
    "mysql": "preferred_database",
    "sqlite": "preferred_database",
    "mongodb": "preferred_database",
    "sqlalchemy": "preferred_orm",
    "docker": "preferred_container",
    "jwt": "preferred_auth",
}

_STYLE_PATTERNS = (
    (re.compile(r"отвечай\s+кратко|краткие\s+ответы|покороче", re.IGNORECASE),
     "response_style", "concise"),
    (re.compile(r"отвечай\s+подробно|подробные\s+ответы", re.IGNORECASE),
     "response_style", "detailed"),
    (re.compile(r"отвечай\s+на\s+русском|по-русски", re.IGNORECASE),
     "response_language", "ru"),
    (re.compile(r"отвечай\s+на\s+английском|in\s+english", re.IGNORECASE),
     "response_language", "en"),
)


def _clean_fragment(text: str) -> str:
    """Trim a captured fragment down to a usable value.

    The fragment is cut at the first sentence boundary, otherwise a preference
    like "предпочитаю Python. Сейчас мы разрабатываем API" would swallow the
    following, unrelated statement.
    """
    value = text.strip()
    value = re.split(r"[.!?;\n]", value, maxsplit=1)[0]
    value = value.strip().strip(",;:")
    value = re.sub(r"\s+", " ", value)
    return value[:200]


def _split_items(text: str) -> List[str]:
    """Split "Python и FastAPI" / "Python, FastAPI" into separate items."""
    parts = re.split(r"\s*(?:,|;|\s+и\s+|\s+and\s+|\s*\+\s*)\s*", text)
    return [part.strip() for part in parts if part.strip()]


class MemoryExtractor:
    """Classifies a message into memory layers. Never writes to the database."""

    def __init__(
        self, client: Optional[AIClient] = None, *, model: Optional[str] = None
    ) -> None:
        self._client = client
        self.model = model

    async def extract(
        self,
        user_message: str,
        *,
        assistant_message: str = "",
        working_memory_context: str = "",
        long_term_context: str = "",
    ) -> MemoryExtractionResult:
        """Analyse a message and return candidates for each layer."""
        if self._client is not None:
            try:
                result = await self._extract_with_llm(
                    user_message,
                    assistant_message=assistant_message,
                    working_memory_context=working_memory_context,
                    long_term_context=long_term_context,
                )
                if result is not None:
                    return result
            except Exception as exc:  # noqa: BLE001 - fall back to rules
                logger.warning(
                    "[MEMORY] LLM-извлечение не удалось (%s), использую правила",
                    type(exc).__name__,
                )

        return self.extract_with_rules(user_message)

    # -------------------------------------------------------------------- LLM
    async def _extract_with_llm(
        self,
        user_message: str,
        *,
        assistant_message: str,
        working_memory_context: str,
        long_term_context: str,
    ) -> Optional[MemoryExtractionResult]:
        assert self._client is not None
        parts = [f"Сообщение пользователя:\n{user_message}"]
        if assistant_message:
            parts.append(f"Ответ ассистента:\n{assistant_message[:1000]}")
        if working_memory_context:
            parts.append(f"Текущая рабочая память:\n{working_memory_context}")
        if long_term_context:
            parts.append(f"Уже известные долговременные факты:\n{long_term_context}")
        parts.append("Верни JSON по описанной схеме.")

        raw = await self._complete(parts)

        payload = self._parse_json(raw)
        if payload is None:
            return None
        return self._to_result(payload)

    async def _complete(self, parts: List[str]) -> str:
        """Call the model with the extraction prompt."""
        assert self._client is not None
        if not self.model:
            raise RuntimeError("Модель не задана для извлечения памяти")
        return await self._client.complete(
            self.model,
            [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": "\n\n".join(parts)},
            ],
        )

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        """Extract a JSON object from a model answer, tolerating markdown fences."""
        if not raw:
            return None
        text = raw.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fence:
            text = fence.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _to_result(payload: dict) -> MemoryExtractionResult:
        working_raw = payload.get("working_memory")
        patch: Optional[WorkingMemoryPatch] = None
        if isinstance(working_raw, dict):
            candidate = WorkingMemoryPatch(
                task=_optional_str(working_raw.get("task")),
                goal=_optional_str(working_raw.get("goal")),
                stack=_str_list(working_raw.get("stack")),
                current_step=_optional_str(working_raw.get("current_step")),
                completed=_str_list(working_raw.get("completed")),
                constraints=_str_list(working_raw.get("constraints")),
                decisions=_str_list(working_raw.get("decisions")),
            )
            if not candidate.is_empty():
                patch = candidate

        candidates: List[LongTermCandidate] = []
        raw_candidates = payload.get("long_term_memory")
        if isinstance(raw_candidates, list):
            for item in raw_candidates:
                if not isinstance(item, dict):
                    continue
                key = _optional_str(item.get("key"))
                value = _optional_str(item.get("value"))
                if not key or not value:
                    continue
                category = item.get("category")
                if category not in ("preference", "decision", "fact", "constraint"):
                    category = "fact"
                try:
                    confidence = float(item.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                candidates.append(
                    LongTermCandidate(
                        category=category,
                        key=key,
                        value=value,
                        confidence=max(0.0, min(1.0, confidence)),
                    )
                )

        return MemoryExtractionResult(
            short_term=bool(payload.get("short_term", True)),
            working_memory=patch,
            long_term_candidates=candidates,
            summary=_optional_str(payload.get("summary")) or "",
            source="llm",
        )

    # ------------------------------------------------------------------ rules
    def extract_with_rules(self, user_message: str) -> MemoryExtractionResult:
        """Deterministic fallback classification.

        Used when no API is configured or the model answer is unusable, so the
        memory model still works offline and in tests.
        """
        text = (user_message or "").strip()
        patch = WorkingMemoryPatch()
        candidates: List[LongTermCandidate] = []
        notes: List[str] = []

        # Preferences are extracted first and removed from the text, so the
        # remaining sentence is not misread as a task statement.
        task_text = text
        for pattern in _PREFERENCE_PATTERNS:
            match = pattern.search(task_text)
            if not match:
                continue
            fragment = _clean_fragment(match.group(1))
            for item in _split_items(fragment):
                lowered = item.lower()
                tech = next((t for t in _KNOWN_TECH if t in lowered), None)
                if tech:
                    candidates.append(
                        LongTermCandidate(
                            category="preference",
                            key=_TECH_KEY_HINTS.get(tech, "preferred_technology"),
                            value=item,
                            confidence=0.8,
                        )
                    )
                else:
                    candidates.append(
                        LongTermCandidate(
                            category="preference",
                            key="preference",
                            value=item,
                            confidence=0.6,
                        )
                    )
            task_text = task_text[: match.start()] + " " + task_text[match.end() :]
            break

        for pattern in _TASK_PATTERNS:
            match = pattern.search(task_text)
            if match:
                patch.task = _clean_fragment(match.group(1))
                notes.append("task")
                break

        for pattern in _STEP_PATTERNS:
            match = pattern.search(task_text)
            if match:
                patch.current_step = _clean_fragment(match.group(1))
                notes.append("current_step")
                break

        for pattern in _DECISION_PATTERNS:
            match = pattern.search(task_text)
            if match:
                decision = _clean_fragment(match.group(1))
                patch.decisions = [decision]
                notes.append("decisions")
                break

        for pattern in _CONSTRAINT_PATTERNS:
            match = pattern.search(task_text)
            if match:
                patch.constraints = [_clean_fragment(match.group(1))]
                notes.append("constraints")
                break

        for pattern, key, value in _STYLE_PATTERNS:
            if pattern.search(text):
                candidates.append(
                    LongTermCandidate(
                        category="preference",
                        key=key,
                        value=value,
                        confidence=0.85,
                    )
                )

        # A bare technology mention inside a task statement is a working-memory
        # stack item, not a durable user preference.
        if patch.task or patch.current_step:
            stack = [
                tech
                for tech in _KNOWN_TECH
                if re.search(rf"\b{re.escape(tech)}\b", task_text, re.IGNORECASE)
            ]
            if stack:
                patch.stack = [tech.title() if tech.islower() else tech for tech in stack]
                notes.append("stack")

        return MemoryExtractionResult(
            short_term=True,
            working_memory=patch if not patch.is_empty() else None,
            long_term_candidates=candidates,
            summary=", ".join(notes) if notes else "только текущий диалог",
            source="rules",
        )


def _optional_str(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _str_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]