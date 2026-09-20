"""Task state extraction — stage, current step and expected action.

The whole task state is derived from the conversation in **one** model call:
which stage the task is at, what is being done right now and what should happen
next. Asking once keeps the three fields consistent with each other.

Like :class:`~backend.memory.extractor.MemoryExtractor`, this component is
side-effect free: it returns a proposal and never writes to the database. The
:class:`~backend.tasks.manager.TaskStateManager` decides what to store, and it
still validates the proposed stage against the state machine.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from backend.services.ai_client import AIClient
from backend.tasks.models import STAGE_ORDER, TaskStepSuggestion
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

STEP_SYSTEM_PROMPT = """\
Ты — компонент Task State Extractor в приложении AI-чата.
Ты определяешь состояние задачи: на каком она этапе, что делается сейчас и что
нужно сделать дальше.

Тебе дают:
- текущий этап задачи (planning / execution / validation / done);
- уже известные шаг и ожидаемое действие;
- последние сообщения диалога.

Верни СТРОГО JSON без пояснений и без markdown:
{
  "stage": "planning" | "execution" | "validation" | "done",
  "current_step": "краткое описание того, что делается СЕЙЧАС",
  "expected_action": "краткое описание следующего конкретного действия",
  "confidence": 0.0-1.0
}

Этапы идут строго по порядку:
- planning   — задача обсуждается, план ещё не утверждён;
- execution  — план принят, идёт реализация;
- validation — реализация закончена, идёт проверка;
- done       — задача полностью завершена.

Правила для stage:
- этап может двигаться только вперёд: planning → execution → validation → done;
- НЕ перескакивай этапы: если сейчас planning, а работа уже началась, верни
  execution, а не validation или done;
- если задача уже завершена, верни done;
- если из диалога непонятно, что этап изменился, верни текущий этап.

Правила для шага:
- пиши по-русски, коротко (до 12 слов), в форме действия;
- current_step — что уже начато или обсуждается прямо сейчас;
- expected_action — что должно быть сделано следующим шагом;
- если из диалога это не следует, верни пустые строки и confidence 0;
- НЕ выдумывай шагов, которых нет в диалоге;
- НЕ повторяй уже завершённые шаги.
"""

#: How many trailing messages are sent to the model.
MAX_CONTEXT_MESSAGES = 12

#: Below this confidence the suggestion is ignored.
MIN_CONFIDENCE = 0.4


class TaskStepExtractor:
    """Derives the current step and the expected action from a dialogue."""

    def __init__(
        self, client: Optional[AIClient] = None, *, model: Optional[str] = None
    ) -> None:
        self._client = client
        self.model = model

    async def extract(
        self,
        *,
        stage: str,
        current_step: str = "",
        expected_action: str = "",
        history: Optional[List[dict]] = None,
    ) -> TaskStepSuggestion:
        """Ask the model what the current step and next action are."""
        if self._client is None or not self.model:
            return TaskStepSuggestion(source="unavailable")

        try:
            raw = await self._complete(
                stage=stage,
                current_step=current_step,
                expected_action=expected_action,
                history=history or [],
            )
        except Exception as exc:  # noqa: BLE001 - never break the chat
            logger.warning(
                "[TASK] Не удалось извлечь шаг задачи (%s)", type(exc).__name__
            )
            return TaskStepSuggestion(source="error")

        payload = self._parse_json(raw)
        if payload is None:
            logger.debug("[TASK] Модель вернула неразбираемый ответ для шага")
            return TaskStepSuggestion(source="unparsed")

        return self._to_suggestion(payload)

    async def _complete(
        self,
        *,
        stage: str,
        current_step: str,
        expected_action: str,
        history: List[dict],
    ) -> str:
        assert self._client is not None
        assert self.model is not None

        parts = [
            f"Текущий этап: {stage}",
            f"Известный шаг: {current_step or '—'}",
            f"Известное ожидаемое действие: {expected_action or '—'}",
        ]
        if history:
            lines = [
                f"{item.get('role', 'user')}: {item.get('content', '')[:400]}"
                for item in history[-MAX_CONTEXT_MESSAGES:]
            ]
            parts.append("Последние сообщения диалога:\n" + "\n".join(lines))
        parts.append("Верни JSON по описанной схеме.")

        return await self._client.complete(
            self.model,
            [
                {"role": "system", "content": STEP_SYSTEM_PROMPT},
                {"role": "user", "content": "\n\n".join(parts)},
            ],
        )

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        """Extract a JSON object from a model answer, tolerating fences."""
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
    def _to_suggestion(payload: dict) -> TaskStepSuggestion:
        step = str(payload.get("current_step") or "").strip()
        action = str(payload.get("expected_action") or "").strip()

        # An unknown stage is dropped rather than guessed: the manager would
        # reject it anyway, and a wrong stage is worse than no stage.
        raw_stage = str(payload.get("stage") or "").strip().lower()
        stage = raw_stage if raw_stage in STAGE_ORDER else None

        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        # A suggestion with no content is not usable, whatever the confidence.
        if not step and not action and stage is None:
            confidence = 0.0

        return TaskStepSuggestion(
            stage=stage,
            current_step=step,
            expected_action=action,
            confidence=confidence,
            source="llm",
        )

    @staticmethod
    def is_usable(suggestion: TaskStepSuggestion) -> bool:
        """Whether a suggestion is confident enough to be stored."""
        return suggestion.confidence >= MIN_CONFIDENCE and not suggestion.is_empty()