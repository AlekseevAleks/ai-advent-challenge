"""Fact extraction — reading the values transition conditions need.

A transition rule checks its conditions against the task's *facts*
(``plan_status = approved``, ``implementation_status = completed``, …). Those
values are usually stated by the user in the message itself ("план утверждён,
начинаем реализацию"), so asking the user to type them by hand is busywork.

This component reads the user's message and proposes a value for each fact the
active rules actually read. Like the other extractors it is side-effect free:
it returns a proposal and never writes to the database. The
:class:`~backend.transitions.manager.TransitionManager` decides what is stored,
and it only accepts values for fields the rules reference — the model cannot
invent a fact, and it cannot forge the machine position.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from backend.services.ai_client import AIClient
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

FACT_SYSTEM_PROMPT = """\
Ты — компонент Fact Extractor в приложении AI-чата.
Задача находится в некотором состоянии жизненного цикла, и переходы между
состояниями зависят от фактов задачи.

Тебе дают:
- список фактов, которые читают правила переходов, с их текущими значениями;
- последние сообщения диалога;
- сообщение пользователя.

Твоя задача — определить, какие из этих фактов следуют из сообщения
пользователя, и вернуть их значения.

Верни СТРОГО JSON без пояснений и без markdown:
{
  "facts": {
    "имя_факта": "значение"
  },
  "confidence": 0.0-1.0
}

Правила:
- возвращай ТОЛЬКО те факты, которые есть в списке запрошенных;
- НЕ выдумывай новые имена фактов;
- если из сообщения не следует значение факта, НЕ включай его в ответ;
- значение пиши так, как его называет пользователь, коротко (1-3 слова);
- если пользователь говорит, что план утверждён, верни
  "plan_status": "утверждён";
- если пользователь говорит, что реализация завершена, верни
  "implementation_status": "завершена";
- если пользователь говорит, что проверка пройдена, верни
  "validation_status": "пройдена";
- если сообщение не содержит сведений о фактах, верни пустой объект facts;
- confidence — насколько ты уверен в извлечённых значениях.
"""

#: How many trailing messages are sent to the model.
MAX_CONTEXT_MESSAGES = 8

#: Below this confidence the proposal is ignored.
MIN_CONFIDENCE = 0.5


class FactExtractor:
    """Proposes fact values read from the user's message. Writes nothing."""

    def __init__(
        self, client: Optional[AIClient] = None, *, model: Optional[str] = None
    ) -> None:
        self._client = client
        self.model = model

    async def extract(
        self,
        *,
        request: str,
        fields: List[str],
        current: Optional[Dict[str, str]] = None,
        history: Optional[List[dict]] = None,
    ) -> Dict[str, str]:
        """Propose values for the given fact names.

        Returns only the fields that are both requested and present in the
        model's answer; anything else is dropped, so a hallucinated fact name
        never reaches the database.
        """
        if not fields:
            return {}
        if self._client is None or not self.model:
            return {}

        try:
            raw = await self._complete(
                request=request,
                fields=fields,
                current=current or {},
                history=history or [],
            )
        except Exception as exc:  # noqa: BLE001 - never break the chat
            logger.warning(
                "[FACT] Извлечение фактов не удалось (%s)", type(exc).__name__
            )
            return {}

        payload = self._parse_json(raw)
        if payload is None:
            logger.debug("[FACT] Модель вернула неразбираемый ответ")
            return {}

        return self._to_facts(payload, fields)

    async def _complete(
        self,
        *,
        request: str,
        fields: List[str],
        current: Dict[str, str],
        history: List[dict],
    ) -> str:
        assert self._client is not None
        assert self.model is not None

        lines = [
            f"- {name}: {current.get(name) or 'не задан'}" for name in fields
        ]
        parts = ["Факты, которые читают правила переходов:\n" + "\n".join(lines)]
        if history:
            context = [
                f"{item.get('role', 'user')}: {item.get('content', '')[:400]}"
                for item in history[-MAX_CONTEXT_MESSAGES:]
            ]
            parts.append("Последние сообщения диалога:\n" + "\n".join(context))
        parts.append(f"Сообщение пользователя:\n{request}")
        parts.append("Верни JSON по описанной схеме.")

        return await self._client.complete(
            self.model,
            [
                {"role": "system", "content": FACT_SYSTEM_PROMPT},
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
    def _to_facts(payload: dict, fields: List[str]) -> Dict[str, str]:
        """Keep only requested fields with a usable value.

        A field the rules do not read is dropped rather than stored: the model
        must not be able to add facts of its own.
        """
        raw_facts = payload.get("facts")
        if not isinstance(raw_facts, dict):
            return {}

        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < MIN_CONFIDENCE:
            return {}

        allowed = {name.strip() for name in fields if name and name.strip()}
        facts: Dict[str, str] = {}
        for key, value in raw_facts.items():
            name = str(key).strip()
            if name not in allowed:
                continue
            text = str(value if value is not None else "").strip()
            if not text:
                continue
            facts[name] = text[:200]
        return facts
