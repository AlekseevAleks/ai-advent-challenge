"""Contextual Query: превращает короткий/местоименный вопрос в полноценный
поисковый запрос, используя Task Memory и недавнюю историю.

Query Rewrite НЕ изменяет смысл запроса и НЕ добавляет требований, которых нет
у пользователя. Он лишь разрешает местоимения и добавляет текущий фокус и цель,
чтобы поиск по FAISS был осмысленным.
"""

from __future__ import annotations

import re
from typing import List, Optional

from .task_memory import TaskState

_FOLLOWUP_OPENERS = ("а ", "и ", "но ", "почему", "зачем", "какой", "как насчёт", "а что", "и что")


def _is_follow_up(message: str) -> bool:
    low = message.lower()
    return any(low.startswith(p) for p in _FOLLOWUP_OPENERS) or len(message.strip()) <= 60


def build_contextual_query(
    message: str,
    task_state: TaskState,
    history: Optional[List[dict]] = None,
) -> str:
    msg = message.strip()
    low = msg.lower()
    focus = task_state.current_focus
    goal = task_state.goal

    # 1. Разрешаем местоимения/короткие уточнения через фокус
    enriched = msg
    if _is_follow_up(msg):
        if focus and "rerank" in low and focus not in low:
            enriched = re.sub(r"\bкакой\s+лучше\b", f"какой {focus} лучше", enriched, count=1)
            if enriched == msg and "rerank" not in low and "какой" in low:
                enriched = f"{msg} {focus}"
        elif focus and focus not in low:
            enriched = f"{msg} {focus}"

    # 2. Добавляем контекст цели (не меняя смысл, только ориентация поиска)
    if goal and goal.lower() not in enriched.lower():
        goal_ctx = _goal_phrase(goal)
        enriched = f"{enriched} {goal_ctx}".strip()

    # 3. На случай совсем пустой темы — добавляем активные решения как ключевые слова
    active = " ".join(sorted({d.value for d in task_state.decisions if d.status == "active"}))
    if active and active.lower() not in enriched.lower():
        enriched = f"{enriched} ({active})".strip()

    return enriched if enriched.strip() else message


def _goal_phrase(goal: str) -> str:
    low = goal.lower()
    if "rag" in low or "сервис" in low or "поиск" in low:
        return f"в контексте: {goal}".strip()
    return f"в контексте: {goal}".strip()
