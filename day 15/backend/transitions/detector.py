"""Transition detection — the model decides *whether* a move is needed.

The AI is allowed to notice that the task has moved on ("план утверждён,
начинаем реализацию") and to ask for the transition. It is not allowed to
perform it: this component only *proposes*, and
:class:`~backend.transitions.manager.TransitionManager` decides, using the rules
the user configured.

Like the other extractors it is side-effect free and never writes to the
database.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from backend.services.ai_client import AIClient
from backend.transitions.models import TransitionSuggestion
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

TRANSITION_SYSTEM_PROMPT = """\
Ты — компонент Transition Detector в приложении AI-чата.
Ты определяешь, нужно ли перевести задачу в другое состояние жизненного цикла.

Тебе дают:
- текущее состояние задачи;
- список разрешённых переходов из него с их условиями;
- последние сообщения диалога.

Верни СТРОГО JSON без пояснений и без markdown:
{
  "to_state": "id состояния из списка разрешённых переходов" | null,
  "reason": "почему переход нужен, коротко",
  "confidence": 0.0-1.0
}

Правила:
- предлагай переход ТОЛЬКО в состояние из списка разрешённых переходов;
- если из диалога не следует, что задача перешла на следующий этап, верни
  to_state = null;
- НЕ предлагай переход, если пользователь просто обсуждает задачу;
- НЕ выдумывай состояния, которых нет в списке;
- если пользователь явно говорит, что этап завершён (план утверждён, работа
  сделана, проверка пройдена), предложи соответствующий переход;
- confidence — насколько ты уверен, что момент перехода наступил.
"""

#: The pre-flight variant: the request has not been executed yet, so the model
#: is asked which state the task will be in *after* carrying it out.
GATE_SYSTEM_PROMPT = """\
Ты — компонент Transition Detector в приложении AI-чата.
Задача уже начата и находится в некотором состоянии жизненного цикла.

Пользователь прислал запрос. Ты должен решить, в какое состояние перейдёт
задача ПОСЛЕ выполнения этого запроса.

Тебе дают:
- текущее состояние задачи;
- список переходов, разрешённых из него, с их условиями;
- последние сообщения диалога;
- запрос пользователя, который ещё НЕ выполнен.

Верни СТРОГО JSON без пояснений и без markdown:
{
  "to_state": "id состояния из списка разрешённых переходов" | null,
  "reason": "почему выполнение запроса приведёт к этому состоянию, коротко",
  "confidence": 0.0-1.0
}

Правила:
- выбирай ТОЛЬКО из списка разрешённых переходов;
- если выполнение запроса не меняет состояние задачи (обычный вопрос,
  уточнение, обсуждение), верни to_state = null;
- если запрос явно переводит задачу на следующий этап (план утверждён и
  начинается реализация, реализация завершена, проверка пройдена), верни
  соответствующее состояние;
- НЕ выдумывай состояния, которых нет в списке;
- confidence — насколько ты уверен, что запрос приведёт именно к этому
  состоянию.

ВАЖНО: ты определяешь только НАМЕРЕНИЕ запроса — к какому состоянию он ведёт.
Ты НЕ проверяешь условия перехода и НЕ решаешь, разрешён ли переход: это
делает TransitionManager по правилам пользователя. Поэтому:
- если запрос явно просит начать реализацию, верни to_state = "execution",
  даже если условие перехода сейчас не выполнено;
- не отказывайся от ответа из-за неизвестных тебе значений условий;
- если запрос не двигает задачу, верни to_state = null.
"""

#: How many trailing messages are sent to the model.
MAX_CONTEXT_MESSAGES = 10

#: Below this confidence the proposal is ignored.
MIN_CONFIDENCE = 0.5


class TransitionDetector:
    """Proposes a transition based on the dialogue. Never writes anything."""

    def __init__(
        self, client: Optional[AIClient] = None, *, model: Optional[str] = None
    ) -> None:
        self._client = client
        self.model = model

    async def detect(
        self,
        *,
        stage: str,
        available: List[dict],
        history: Optional[List[dict]] = None,
    ) -> TransitionSuggestion:
        """Ask the model whether the task should move on."""
        return await self._ask(
            system_prompt=TRANSITION_SYSTEM_PROMPT,
            stage=stage,
            available=available,
            history=history,
            request="",
        )

    async def detect_for_request(
        self,
        *,
        stage: str,
        available: List[dict],
        request: str,
        history: Optional[List[dict]] = None,
    ) -> TransitionSuggestion:
        """Decide which state the task will be in *after* the request is done.

        This is the pre-flight question: the request has not been executed yet,
        so the answer decides whether it may be executed at all.
        """
        return await self._ask(
            system_prompt=GATE_SYSTEM_PROMPT,
            stage=stage,
            available=available,
            history=history,
            request=request,
        )

    async def _ask(
        self,
        *,
        system_prompt: str,
        stage: str,
        available: List[dict],
        history: Optional[List[dict]],
        request: str,
    ) -> TransitionSuggestion:
        """Shared model call for both detection modes."""
        if not available:
            return TransitionSuggestion(source="no-transitions")
        if self._client is None or not self.model:
            return TransitionSuggestion(source="unavailable")

        try:
            raw = await self._complete(
                system_prompt=system_prompt,
                stage=stage,
                available=available,
                history=history or [],
                request=request,
            )
        except Exception as exc:  # noqa: BLE001 - never break the chat
            logger.warning(
                "[TRANSITION] Определение перехода не удалось (%s)",
                type(exc).__name__,
            )
            return TransitionSuggestion(source="error")

        payload = self._parse_json(raw)
        if payload is None:
            logger.debug("[TRANSITION] Модель вернула неразбираемый ответ")
            return TransitionSuggestion(source="unparsed")

        return self._to_suggestion(payload, available)

    async def _complete(
        self,
        *,
        system_prompt: str,
        stage: str,
        available: List[dict],
        history: List[dict],
        request: str = "",
    ) -> str:
        assert self._client is not None
        assert self.model is not None

        lines = [
            f"- {item.get('from_state')} → {item.get('to_state')}"
            f" | condition: {item.get('condition') or 'нет дополнительных условий'}"
            for item in available
        ]
        parts = [
            f"Текущее состояние: {stage}",
            "Разрешённые переходы:\n" + "\n".join(lines),
        ]
        if history:
            context = [
                f"{item.get('role', 'user')}: {item.get('content', '')[:400]}"
                for item in history[-MAX_CONTEXT_MESSAGES:]
            ]
            parts.append("Последние сообщения диалога:\n" + "\n".join(context))
        if request:
            parts.append(f"Запрос пользователя (ещё не выполнен):\n{request}")
        parts.append("Верни JSON по описанной схеме.")

        return await self._client.complete(
            self.model,
            [
                {"role": "system", "content": system_prompt},
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
    def _to_suggestion(
        payload: dict, available: List[dict]
    ) -> TransitionSuggestion:
        """Keep only a target that is actually among the allowed transitions.

        A state the model invented is dropped rather than guessed: the manager
        would reject it anyway, and a wrong target is worse than none.
        """
        allowed = {
            str(item.get("to_state") or "").strip() for item in available
        }
        raw_target = str(payload.get("to_state") or "").strip()
        target = raw_target if raw_target in allowed else None

        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        if target is None:
            confidence = 0.0

        return TransitionSuggestion(
            to_state=target,
            reason=str(payload.get("reason") or "").strip(),
            confidence=confidence,
            source="llm",
        )

    @staticmethod
    def is_usable(suggestion: TransitionSuggestion) -> bool:
        """Whether a proposal is confident enough to be attempted."""
        return (
            suggestion.confidence >= MIN_CONFIDENCE
            and not suggestion.is_empty()
        )
