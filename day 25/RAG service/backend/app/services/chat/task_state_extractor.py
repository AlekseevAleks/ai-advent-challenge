"""Task State Extractor: консервативное, детерминированное извлечение обновлений
Task Memory из пользовательского сообщения.

Важно: НЕ выдумываем факты. Обновления применяются только из прямых утверждений
пользователя. Каждое решение снабжается source="user_message" и message_id.
Для смены решения используется тот же `key`, что и раньше, чтобы старое решение
стало `superseded` автоматически.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

# Ключи решений по известным технологиям/понятиям
TECH_KEY: Dict[str, str] = {
    "faiss": "vector_store",
    "chroma": "vector_store",
    "nomic-embed-text": "embedding_model",
    "bge": "reranker",
    "bge-reranker": "reranker",
    "reranker": "reranker",
    "rerank": "reranker",
}


def _goal_from(message: str) -> Optional[str]:
    m = re.search(
        r"(?:хочу\s+создать|нужно\s+создать|нужно\s+сделать|хочу\s+сделать|задача\s*[:—]\s*|создаём\s+|делаем\s+)(.+?)[.!?]?\s*$",
        message, re.I | re.S,
    )
    if m:
        g = m.group(1).strip()
        if g and len(g) > 2:
            return g
    return None


def _constraints_from(message: str) -> List[str]:
    out = []
    # «должен работать локально», «только локально», «без облака»
    m = re.search(r"долж(?:ен|на|но)\s+(работать\s+)?(локально|оффлайн)[\w\s]*", message, re.I)
    if m:
        out.append("работать локально")
    if re.search(r"локально", message, re.I) and not re.search(r"должен.*локально", message, re.I):
        out.append("работать локально")
    # «документы будут PDF»
    m = re.search(r"документ(?:ы|ов)?\s+(?:будут|буду)\s+([\w\-]+)", message, re.I)
    if m and m.group(1).lower() not in ("txt", "text"):
        out.append(f"формат документов: {m.group(1).rstrip('.,')}")
    # «используем X» as constraint for non-decisions (embedding)
    m = re.search(r"используем\s+(nomic-embed-text|ollama)", message, re.I)
    if m:
        out.append(f"embeddings: {m.group(1).lower()}")
    return out


def _keyword(message: str) -> Optional[str]:
    m = re.search(r"(faiss|chroma|nomic-embed-text|bge-reranker|reranker|rerank|ollama)", message, re.I)
    return m.group(1).lower() if m else None


def _decisions_from(message: str) -> List[tuple]:
    """Вернуть список (key, value) новых решений из сообщения."""
    out: List[tuple] = []
    # «используем <tech>» и «оставим <tech>»
    for m in re.finditer(r"(?:используем|оставим|выберем|используем\s+только)\s+([\w\-]+)", message, re.I):
        val = m.group(1).lower().rstrip(".,")
        key = TECH_KEY.get(val)
        if key:
            out.append((key, val))
    # «передумал насчёт X. теперь используем Y»
    m = re.search(r"передумал\s+насчёт\s+([\w\-]+).*?(?:используем|берём|теперь)\s+([\w\-]+)", message, re.I | re.S)
    if m:
        old = m.group(1).lower()
        new = m.group(2).lower().rstrip(".,")
        key = TECH_KEY.get(old) or TECH_KEY.get(new)
        if key and new:
            out.append((key, new))
    # размер чанка: «чанк(и)? будет N токенов/символов»
    m = re.search(r"(?:чанк\w*|chunk\w*)\s+будет\s+(\d+)\s+(токен\w*|символ\w*)", message, re.I)
    if m:
        out.append(("chunk_size", f"{m.group(1)} {m.group(2).rstrip(',.')}"))
    # overlap: «overlap — N», «перекрытие N»
    m = re.search(r"(?:overlap|перекрытие)\w*\s*[—:\-]?\s*(\d+)\s+(токен\w*|символ\w*)", message, re.I)
    if m:
        out.append(("overlap", f"{m.group(1)} {m.group(2).rstrip(',.')}"))
    # PDF constraint counts as decision «документы: pdf»
    m = re.search(r"документ(?:ы|ов)?\s+(?:будут|буду)\s+pdf", message, re.I)
    if m:
        out.append(("document_format", "pdf"))
    return out


def _focus_from(message: str, state) -> Optional[str]:
    m = re.search(r"(?:расскажи|покажи|объясни|про)\s+про\s+([\w\-]+)", message, re.I)
    if m:
        return m.group(1).lower()
    m = re.search(r"зачем\s+он\s+нужен", message, re.I)
    if m and state.active_decision("reranker"):
        return "reranker"
    if re.search(r"какой\s+reranker", message, re.I):
        return "reranker"
    if re.search(r"rerank", message, re.I):
        return "reranker"
    return state.current_focus


def extract_task_update(message: str, state, message_id: Optional[str] = None) -> dict:
    """Вернуть детерминированное обновление Task Memory (без применения)."""
    goal = _goal_from(message)
    constraints = _constraints_from(message)
    decisions = _decisions_from(message)
    focus = _focus_from(message, state)
    open_questions: List[str] = []
    if re.search(r"как\s+проверить качество|как понять|что лучше", message, re.I):
        open_questions.append(message.strip())
    return {
        "goal": goal,
        "constraints": constraints,
        "decisions": decisions,
        "focus": focus,
        "open_questions": open_questions,
        "message_id": message_id,
    }


def apply_task_update(state, update: dict):
    """Применить обновление к TaskState (bump version при изменениях)."""
    if update.get("goal"):
        state.set_goal(update["goal"])
    for c in update.get("constraints", []):
        state.add_constraint(c)
    for key, value in update.get("decisions", []):
        state.add_decision(key, value, source="user_message", message_id=update.get("message_id"))
    if update.get("focus"):
        state.set_focus(update["focus"])
    for q in update.get("open_questions", []):
        state.add_open_question(q)
    return state
