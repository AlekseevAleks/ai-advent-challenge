"""Invariant conflict detection.

Before a request reaches the model, the active invariants are checked against
it. This module asks the model to decide whether the request asks for something
an invariant forbids, and whether the user explicitly asked to change a rule.

Like the other extractors, it is side-effect free: it returns a proposal and
never writes to the database. :class:`~backend.invariants.manager.InvariantManager`
validates the proposal, so the model cannot invent a rule that does not exist.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from backend.invariants.models import (
    ConflictCheckResult,
    Invariant,
    InvariantConflict,
)
from backend.services.ai_client import AIClient
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

CONFLICT_SYSTEM_PROMPT = """\
Ты — компонент Invariant Conflict Detector в приложении AI-чата.
Твоя задача — проверить, нарушает ли запрос пользователя активные инварианты
проекта, и не просит ли пользователь явно изменить сам инвариант.

Инвариант — это обязательное ограничение. Обычный запрос НЕ отменяет инвариант.
Изменить инвариант можно только по явной просьбе пользователя.

Верни СТРОГО JSON без пояснений и без markdown:
{
  "has_conflict": true | false,
  "conflicts": [
    {
      "invariant_id": "id инварианта из списка",
      "rule": "текст правила",
      "requested": "что именно в запросе нарушает правило",
      "reason": "почему это конфликт"
    }
  ],
  "alternative": "решение, удовлетворяющее всем активным инвариантам, или пустая строка",
  "explicit_change": true | false,
  "change_targets": ["id инварианта, который пользователь просит изменить"]
}

Правила:
- конфликт есть только если запрос действительно требует нарушить правило;
- если запрос не противоречит правилам, верни has_conflict=false и пустой список;
- НЕ придумывай инварианты, которых нет в списке;
- explicit_change=true только если пользователь прямо говорит, что решение
  изменилось и просит обновить ограничение (например: «мы приняли новое решение»,
  «теперь используем X», «измени ограничение», «отменяем это ограничение»);
- обычная просьба («добавь Redis») — это НЕ explicit_change, а конфликт;
- alternative заполняй только когда конфликт есть и есть совместимое решение.
"""

#: How many trailing messages are sent as context.
MAX_CONTEXT_MESSAGES = 6


class InvariantConflictDetector:
    """Checks a request against the active invariants."""

    def __init__(
        self, client: Optional[AIClient] = None, *, model: Optional[str] = None
    ) -> None:
        self._client = client
        self.model = model

    async def check(
        self,
        request: str,
        invariants: List[Invariant],
        *,
        history: Optional[List[dict]] = None,
    ) -> ConflictCheckResult:
        """Ask the model whether the request violates any active invariant."""
        if not invariants:
            return ConflictCheckResult(has_conflict=False, source="no-invariants")
        if self._client is None or not self.model:
            return ConflictCheckResult(has_conflict=False, source="unavailable")

        try:
            raw = await self._complete(request, invariants, history or [])
        except Exception as exc:  # noqa: BLE001 - never break the chat
            logger.warning(
                "[INVARIANT] Проверка конфликтов не удалась (%s)",
                type(exc).__name__,
            )
            return ConflictCheckResult(has_conflict=False, source="error")

        payload = self._parse_json(raw)
        if payload is None:
            logger.debug("[INVARIANT] Модель вернула неразбираемый ответ")
            return ConflictCheckResult(has_conflict=False, source="unparsed")

        return self._to_result(payload)

    async def _complete(
        self,
        request: str,
        invariants: List[Invariant],
        history: List[dict],
    ) -> str:
        assert self._client is not None
        assert self.model is not None

        lines = [
            f"- id={invariant.id} | {invariant.data.category} | "
            f"{invariant.data.priority} | {invariant.data.rule}"
            for invariant in invariants
        ]
        parts = ["Активные инварианты:\n" + "\n".join(lines)]
        if history:
            context = [
                f"{item.get('role', 'user')}: {item.get('content', '')[:300]}"
                for item in history[-MAX_CONTEXT_MESSAGES:]
            ]
            parts.append("Последние сообщения диалога:\n" + "\n".join(context))
        parts.append(f"Запрос пользователя:\n{request}")
        parts.append("Верни JSON по описанной схеме.")

        return await self._client.complete(
            self.model,
            [
                {"role": "system", "content": CONFLICT_SYSTEM_PROMPT},
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
    def _to_result(payload: dict) -> ConflictCheckResult:
        conflicts: List[InvariantConflict] = []
        raw_conflicts = payload.get("conflicts")
        if isinstance(raw_conflicts, list):
            for item in raw_conflicts:
                if not isinstance(item, dict):
                    continue
                rule = str(item.get("rule") or "").strip()
                invariant_id = str(item.get("invariant_id") or "").strip()
                if not rule and not invariant_id:
                    continue
                conflicts.append(
                    InvariantConflict(
                        invariant_id=invariant_id,
                        rule=rule,
                        requested=str(item.get("requested") or "").strip(),
                        reason=str(item.get("reason") or "").strip(),
                    )
                )

        targets: List[str] = []
        raw_targets = payload.get("change_targets")
        if isinstance(raw_targets, list):
            targets = [str(item).strip() for item in raw_targets if str(item).strip()]

        has_conflict = bool(payload.get("has_conflict")) and bool(conflicts)

        return ConflictCheckResult(
            has_conflict=has_conflict,
            conflicts=conflicts,
            alternative=str(payload.get("alternative") or "").strip(),
            explicit_change=bool(payload.get("explicit_change")),
            change_targets=targets,
            source="llm",
        )
