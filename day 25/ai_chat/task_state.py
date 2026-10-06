"""Task State — «память задачи», живущая весь диалог.

Модуль реализует объект состояния задачи (Task State), который создаётся
при первом сообщении диалога, обновляется после каждого сообщения
пользователя и (локально) после ответа ассистента, сохраняется между
сессиями и подмешивается в промт в виде компактной сводки.

Жизненный цикл (по шагам из ТЗ):

* ``INIT``   — ``TaskStateEngine.on_user_message`` создаёт пустой state и
  заполняет его первым результатом extractor'а (температура 0, JSON-режим).
* ``UPDATE`` — после каждого сообщения пользователя вызывается extractor
  с жёсткой JSON-схемой :data:`EXTRACTOR_SCHEMA`; результат сливается
  правилами MERGE в существующий state.
* ``MERGE``  — факты не дублируются; при конфликте новое значение получает
  свежий ``ts``, а прежняя запись помечается ``superseded_by``.
* ``INJECT`` — :func:`build_state_summary` собирает компактную сводку
  (≤ :data:`STATE_SUMMARY_MAX_TOKENS` токенов), которая добавляется
  отдельным system-сообщением перед генерацией ответа.
* ``PERSIST``— :class:`TaskStateStore` сохраняет state в
  ``task_states/{chat_id}.json`` после каждого обновления.

Модуль не зависит от FastAPI и других модулей приложения; LLM-вызовы
выполняются через инжектируемый callable ``llm_json(messages) -> dict``
(в проде это ``api_client.complete_json``, в тестах — детерминированный
фейк), поэтому модуль проверяется локально без внешних API.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "task_states")

# Ограничение на размер сводки, подмешиваемой в промт (~4 символа на токен).
STATE_SUMMARY_MAX_TOKENS = 400
# Максимум элементов списков, попадающих в сводку.
SUMMARY_FACTS_LIMIT = 8
SUMMARY_TERMS_LIMIT = 8
SUMMARY_CONSTRAINTS_LIMIT = 6
SUMMARY_QUESTIONS_LIMIT = 5

# Жёсткая JSON-схема для extractor'а (температура 0, response_format json_object).
EXTRACTOR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {
            "type": "string",
            "description": "Единственная формулировка цели текущего диалога. Если цель уже есть — уточняй её, не плоди новые.",
        },
        "goal_changed": {
            "type": "boolean",
            "description": "true, если формулировка цели изменилась относительно предыдущего состояния.",
        },
        "goal_change_reason": {
            "type": "string",
            "description": "Причина смены/уточнения цели (пустая строка, если goal_changed=false).",
        },
        "last_user_intent": {
            "type": "string",
            "description": "Намерение пользователя в текущем сообщении, одной фразой.",
        },
        "confirmed_facts": {
            "type": "array",
            "description": "Актуальные подтверждённые факты (все, известные на данный момент, включая ранее зафиксированные).",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Короткий ключ факта, например 'stack' или 'budget'."},
                    "value": {"type": "string", "description": "Значение факта."},
                },
                "required": ["key", "value"],
            },
        },
        "constraints": {
            "type": "array",
            "description": "Актуальные ограничения (язык, формат, длина, стиль, бюджет, стек, регион и т. п.).",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "Тип ограничения, например 'language' или 'max_length'."},
                    "value": {"type": "string", "description": "Значение ограничения."},
                },
                "required": ["type", "value"],
            },
        },
        "fixed_terms": {
            "type": "array",
            "description": "Зафиксированные термины/сокращения/нейминг, введённые пользователем.",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "definition": {"type": "string"},
                },
                "required": ["term", "definition"],
            },
        },
        "open_questions": {
            "type": "array",
            "description": "Вопросы, которые ещё нужно уточнить у пользователя, чтобы достичь цели.",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["question", "priority"],
            },
        },
        "resolved_questions": {
            "type": "array",
            "description": "Вопросы, на которые ответ уже получен.",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                },
                "required": ["question", "answer"],
            },
        },
        "pending_actions": {
            "type": "array",
            "description": "Действия, которые агент должен выполнить (например, 'написать код', 'подготовить отчёт').",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "status": {"type": "string", "description": "например 'todo', 'done', 'blocked'"},
                },
                "required": ["action", "status"],
            },
        },
    },
    "required": [
        "goal",
        "last_user_intent",
        "confirmed_facts",
        "constraints",
        "fixed_terms",
        "open_questions",
        "resolved_questions",
        "pending_actions",
    ],
    "additionalProperties": False,
}


def _now() -> str:
    """Текущее время в формате ISO-8601 (UTC)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def estimate_tokens(text: str) -> int:
    """Грубая оценка числа токенов: ~4 символа на токен."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Task State: структура + правила MERGE
# ---------------------------------------------------------------------------


class TaskState:
    """Состояние задачи диалога.

    Поля соответствуют обязательной структуре из ТЗ: goal, goal_history,
    confirmed_facts, constraints, fixed_terms, open_questions,
    resolved_questions, rag_context, turn_count, last_user_intent,
    pending_actions.
    """

    def __init__(self, chat_id: str = "") -> None:
        self.chat_id = chat_id
        self.goal: str = ""
        self.goal_history: List[Dict[str, Any]] = []
        self.confirmed_facts: List[Dict[str, Any]] = []
        self.constraints: List[Dict[str, Any]] = []
        self.fixed_terms: List[Dict[str, Any]] = []
        self.open_questions: List[Dict[str, Any]] = []
        self.resolved_questions: List[Dict[str, Any]] = []
        self.rag_context: List[Dict[str, Any]] = []
        self.turn_count: int = 0
        self.last_user_intent: str = ""
        self.pending_actions: List[Dict[str, Any]] = []
        self.updated_at: str = ""

    # --- сериализация ----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Возвращает полное представление state для персистенции."""
        return {
            "chat_id": self.chat_id,
            "goal": self.goal,
            "goal_history": self.goal_history,
            "confirmed_facts": self.confirmed_facts,
            "constraints": self.constraints,
            "fixed_terms": self.fixed_terms,
            "open_questions": self.open_questions,
            "resolved_questions": self.resolved_questions,
            "rag_context": self.rag_context,
            "turn_count": self.turn_count,
            "last_user_intent": self.last_user_intent,
            "pending_actions": self.pending_actions,
            "updated_at": self.updated_at or _now(),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TaskState":
        """Восстанавливает state из словаря (повреждённые поля игнорируются)."""
        state = cls(chat_id=(data or {}).get("chat_id", ""))
        if not isinstance(data, dict):
            return state
        state.goal = str(data.get("goal", "") or "")
        state.goal_history = _list_of_dicts(data.get("goal_history"))
        state.confirmed_facts = _list_of_dicts(data.get("confirmed_facts"))
        state.constraints = _list_of_dicts(data.get("constraints"))
        state.fixed_terms = _list_of_dicts(data.get("fixed_terms"))
        state.open_questions = _list_of_dicts(data.get("open_questions"))
        state.resolved_questions = _list_of_dicts(data.get("resolved_questions"))
        state.rag_context = _list_of_dicts(data.get("rag_context"))
        state.turn_count = int(data.get("turn_count", 0) or 0)
        state.last_user_intent = str(data.get("last_user_intent", "") or "")
        state.pending_actions = _list_of_dicts(data.get("pending_actions"))
        state.updated_at = str(data.get("updated_at", "") or "")
        return state

    # --- MERGE: применение результата extractor'а -------------------------

    def merge_extraction(
        self,
        extraction: Dict[str, Any],
        source_msg_id: str,
        ts: Optional[str] = None,
    ) -> bool:
        """Сливает результат extractor'а в state по правилам MERGE.

        Правила (явные, без «магии»):

        * goal — единственная формулировка; при смене значения предыдущее
          уходит в ``goal_history`` с причиной; повтор того же значения
          в историю не пишется.
        * confirmed_facts/constraints/fixed_terms — запись уникальна по
          ключу (key/type/term); при конфликте значения создаётся НОВАЯ
          запись со свежим ``ts``, а прежняя помечается ``superseded_by``.
        * open_questions — уникальны по тексту; вопросы, которых больше
          нет в выдаче extractor'а, помечаются ``status: "closed"``
          (не задаются повторно).
        * resolved_questions — дедуплицируются по тексту вопроса.
        * pending_actions — уникальны по ``action``, ``status`` обновляется.

        Возвращает ``True``, если состояние изменилось.
        """
        ts = ts or _now()
        changed = False
        extraction = extraction or {}

        # --- goal ---
        new_goal = str(extraction.get("goal", "") or "").strip()
        if new_goal != self.goal:
            self.goal_history.append(
                {
                    "ts": ts,
                    "goal": new_goal,
                    "reason": str(extraction.get("goal_change_reason", "") or "").strip(),
                }
            )
            self.goal = new_goal
            changed = True

        # --- confirmed_facts ---
        new_facts = _as_items(extraction.get("confirmed_facts"), ("key", "value"))
        if self._merge_keyed(
            self.confirmed_facts,
            new_facts,
            "key",
            ts=ts,
            source_msg_id=source_msg_id,
            allowed=("key", "value"),
        ):
            changed = True

        # --- constraints ---
        new_constraints = _as_items(extraction.get("constraints"), ("type", "value"))
        if self._merge_keyed(
            self.constraints,
            new_constraints,
            "type",
            ts=ts,
            source_msg_id=source_msg_id,
            allowed=("type", "value"),
        ):
            changed = True

        # --- fixed_terms ---
        new_terms = _as_items(extraction.get("fixed_terms"), ("term", "definition"))
        if self._merge_keyed(
            self.fixed_terms,
            new_terms,
            "term",
            ts=ts,
            source_msg_id=source_msg_id,
            allowed=("term", "definition"),
        ):
            changed = True

        # --- open_questions (закрываем исчезнувшие) ---
        new_questions = {
            str(item.get("question", "")).strip()
            for item in _as_items(extraction.get("open_questions"), ("question", "priority"))
            if str(item.get("question", "")).strip()
        }
        for item in self.open_questions:
            if (
                item.get("question", "") not in new_questions
                and item.get("status", "open") == "open"
            ):
                item["status"] = "closed"
                item["closed_ts"] = ts
                changed = True
        for question in sorted(new_questions):
            if not any(item.get("question") == question for item in self.open_questions):
                self.open_questions.append(
                    {
                        "question": question,
                        "priority": _question_priority(question, extraction),
                        "ts": ts,
                        "status": "open",
                    }
                )
                changed = True

        # --- resolved_questions (дедупликация по тексту) ---
        for item in _as_items(extraction.get("resolved_questions"), ("question", "answer")):
            question = str(item.get("question", "") or "").strip()
            answer = str(item.get("answer", "") or "").strip()
            if not question:
                continue
            existing = next(
                (r for r in self.resolved_questions if r.get("question") == question), None
            )
            if existing is None:
                self.resolved_questions.append(
                    {"question": question, "answer": answer, "ts": ts}
                )
                changed = True
            elif existing.get("answer") != answer:
                existing["answer"] = answer
                existing["ts"] = ts
                changed = True
            # Закрытый открытый вопрос больше не «открытый».
            for opened in self.open_questions:
                if opened.get("question") == question and opened.get("status", "open") == "open":
                    opened["status"] = "closed"
                    opened["closed_ts"] = ts
                    changed = True

        # --- pending_actions ---
        new_actions = _as_items(extraction.get("pending_actions"), ("action", "status"))
        for item in new_actions:
            action = str(item.get("action", "") or "").strip()
            if not action:
                continue
            existing = next(
                (a for a in self.pending_actions if a.get("action") == action), None
            )
            if existing is None:
                self.pending_actions.append(
                    {"action": action, "status": str(item.get("status", "todo") or "todo"), "ts": ts}
                )
                changed = True
            elif existing.get("status") != item.get("status"):
                existing["status"] = item.get("status")
                existing["ts"] = ts
                changed = True

        # --- last_user_intent / turn_count ---
        intent = str(extraction.get("last_user_intent", "") or "").strip()
        if intent and intent != self.last_user_intent:
            self.last_user_intent = intent
            changed = True
        self.turn_count += 1
        self.updated_at = ts
        return changed or intent != ""

    @staticmethod
    def _merge_keyed(
        records: List[Dict[str, Any]],
        fresh: List[Dict[str, Any]],
        key_field: str,
        *,
        ts: str,
        source_msg_id: str,
        allowed: tuple,
    ) -> bool:
        """MERGE записей, уникальных по ``key_field`` (с пометкой superseded_by)."""
        changed = False
        seen: Dict[str, Dict[str, Any]] = {}
        for item in records:
            key_value = str(item.get(key_field, "") or "")
            if key_value:
                seen[key_value] = item
        for candidate in fresh:
            key_value = str(candidate.get(key_field, "") or "").strip()
            if not key_value:
                continue
            value = str(candidate.get("value", "") or "").strip()
            if candidate.get("definition"):
                value = str(candidate.get("definition", "") or "").strip()
            existing = seen.get(key_value)
            if existing is None:
                record = {
                    key_field: key_value,
                    "value": value if value else "",
                    "ts": ts,
                    "source_msg_id": source_msg_id,
                    "superseded_by": None,
                }
                records.append(record)
                changed = True
            elif existing.get("value") != value:
                # Конфликт значений: новое значение с новым ts,
                # старая запись помечается superseded_by.
                existing["superseded_by"] = ts
                records.append(
                    {
                        key_field: key_value,
                        "value": value,
                        "ts": ts,
                        "source_msg_id": source_msg_id,
                        "superseded_by": None,
                    }
                )
                changed = True
        return changed

    # --- локальное обновление после ответа ассистента ----------------------

    def record_assistant_turn(
        self,
        answer: str,
        sources: Optional[List[Dict[str, Any]]] = None,
        msg_id: str = "",
    ) -> None:
        """Детерминированное (без LLM) обновление state после ответа.

        Отмечает использованные RAG-источники в ``rag_context``
        (``used_in_msg_id``) и закрывает вопросы, на которые ответ
        ассистента уже содержит подсказку цели — закрытие открытых
        вопросов выполняет только extractor (следующий ход), здесь
        фиксируются только источники и счётчик ходов.
        """
        ts = _now()
        for source in sources or []:
            source_id = str(source.get("source_id", "") or "")
            if not source_id:
                continue
            existing = next(
                (r for r in self.rag_context if r.get("source_id") == source_id), None
            )
            if existing is None:
                self.rag_context.append(
                    {
                        "source_id": source_id,
                        "chunk_id": source.get("chunk_id", ""),
                        "url": source.get("url", ""),
                        "score": source.get("score", 0.0),
                        "used_in_msg_id": msg_id,
                        "ts": ts,
                    }
                )
            else:
                existing["used_in_msg_id"] = msg_id
                existing["score"] = source.get("score", existing.get("score", 0.0))
                existing["ts"] = ts
        self.updated_at = ts


def _list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    """Нормализует значение в список словарей (битые элементы отбрасываются)."""
    if not isinstance(value, list):
        return []
    result: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(dict(item))
    return result


def _as_items(value: Any, fields: tuple) -> List[Dict[str, Any]]:
    """Нормализует списки extractor'а: только словари с непустым лидирующим полем."""
    items: List[Dict[str, Any]] = []
    for item in _list_of_dicts(value):
        lead = str(item.get(fields[0], "") or "").strip()
        if lead:
            items.append(dict(item))
    return items


def _question_priority(question: str, extraction: Dict[str, Any]) -> str:
    """Возвращает приоритет вопроса из результата extractor'а (по умолчанию medium)."""
    for item in _as_items(extraction.get("open_questions"), ("question", "priority")):
        if str(item.get("question", "") or "").strip() == question:
            priority = str(item.get("priority", "") or "").strip()
            if priority in ("high", "medium", "low"):
                return priority
    return "medium"


# ---------------------------------------------------------------------------
# Хранилище (PERSIST): task_states/{chat_id}.json
# ---------------------------------------------------------------------------


class TaskStateStore:
    """Сохраняет Task State между сессиями в JSON-файл на диск.

    Файл на чат: ``task_states/{chat_id}.json``. Пользовательские данные
    (config.json, chats.json, logs/) не затрагиваются.
    """

    def __init__(self, directory: str = STATE_DIR) -> None:
        self.directory = directory
        self._lock = threading.RLock()

    def _path(self, chat_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", chat_id or "")
        return os.path.join(self.directory, f"{safe}.json")

    def load(self, chat_id: str) -> TaskState:
        """Читает state чата с диска; при отсутствии/повреждении — пустой."""
        with self._lock:
            try:
                with open(self._path(chat_id), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                data = {}
            state = TaskState.from_dict(data)
            state.chat_id = chat_id
            return state

    def save(self, state: TaskState) -> bool:
        """Пишет state на диск (создавая каталог). Возвращает True при успехе."""
        with self._lock:
            try:
                os.makedirs(self.directory, exist_ok=True)
                path = self._path(state.chat_id)
                tmp = f"{path}.tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(state.to_dict(), fh, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
                return True
            except OSError:
                return False

    def delete(self, chat_id: str) -> bool:
        """Удаляет state чата. Возвращает True, если файл существовал."""
        with self._lock:
            try:
                os.remove(self._path(chat_id))
                return True
            except OSError:
                return False


# ---------------------------------------------------------------------------
# Extractor (UPDATE): детерминированный LLM-вызов с JSON-схемой
# ---------------------------------------------------------------------------

EXTRACTOR_SYSTEM_PROMPT = (
    "Ты — модуль извлечения состояния задачи (Task State extractor). "
    "Твоя задача — по сообщению пользователя и предыдущему состоянию задачи "
    "обновить структурированное состояние. Работай строго по схеме, "
    "temperature=0: никаких догадок, только то, что следует из диалога.\n\n"
    "Правила:\n"
    "- goal — единственная цель диалога; если пользователь что-то уточняет, "
    "уточни формулировку, но не плоди новые цели; если цель не менялась, "
    "повтори прежнюю формулировку дословно и поставь goal_changed=false.\n"
    "- confirmed_facts — ВСЕ актуальные факты, включая ранее зафиксированные "
    "из предыдущего состояния; не теряй их.\n"
    "- constraints — ВСЕ ограничения (язык, формат, длина, стиль, бюджет, "
    "стек, регион и т. п.); при изменении ограничения верни новое значение.\n"
    "- fixed_terms — термины/сокращения, введённые пользователем, с их "
    "значениями; прежние термины тоже сохраняй.\n"
    "- open_questions — вопросы, которые ещё нужно уточнить у пользователя "
    "для достижения цели; если вопрос уже не нужен — не включай его.\n"
    "- resolved_questions — вопросы, на которые ответ уже получен в диалоге.\n"
    "- last_user_intent — намерение пользователя в этом сообщении.\n"
    "- pending_actions — что агент должен сделать по ходу задачи.\n"
    "Ответ — только валидный JSON по схеме."
)


def build_extractor_messages(
    user_text: str,
    prior: TaskState,
    history: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """Собирает сообщения для extractor'а: схема + предыдущее состояние + диалог."""
    prior_text = json.dumps(prior.to_dict(), ensure_ascii=False)
    history_text = ""
    for item in (history or [])[-6:]:
        role = item.get("role", "?")
        content = str(item.get("content", "") or "")
        if content:
            history_text += f"{role}: {content}\n"
    user_payload = (
        f"Предыдущее состояние задачи (JSON):\n{prior_text}\n\n"
        f"Недавний диалог:\n{history_text}\n"
        f"Новое сообщение пользователя:\n{user_text}\n\n"
        "Верни обновлённое состояние в виде JSON по схеме."
    )
    return [
        {
            "role": "system",
            "content": (
                EXTRACTOR_SYSTEM_PROMPT
                + "\n\nJSON-схема ответа:\n"
                + json.dumps(EXTRACTOR_SCHEMA, ensure_ascii=False)
            ),
        },
        {"role": "user", "content": user_payload},
    ]


def normalize_extraction(raw: Any) -> Dict[str, Any]:
    """Приводит ответ extractor'а к словарю (мусор отбрасывается)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except ValueError:
                pass
    return {}


# ---------------------------------------------------------------------------
# Injector (INJECT): компактная сводка для промта (<= 400 токенов)
# ---------------------------------------------------------------------------


def build_state_summary(state: TaskState) -> str:
    """Собирает компактную сводку Task State для system-промта.

    В сводку попадают только релевантные поля: цель, последнее изменение
    цели, актуальные факты/ограничения/термины, открытые вопросы,
    намерение пользователя, счётчик ходов. Актуальными считаются записи
    без ``superseded_by`` и открытые вопросы.
    """
    lines: List[str] = ["Задача (Task State):"]
    if state.goal:
        lines.append(f"- цель: {state.goal}")
    if state.goal_history:
        last = state.goal_history[-1]
        if last.get("reason"):
            lines.append(f"- изменение цели: {last['goal']} (причина: {last['reason']})")

    _append_summary_list(
        lines, "факты", state.confirmed_facts, "key", "value", SUMMARY_FACTS_LIMIT
    )
    _append_summary_list(
        lines, "ограничения", state.constraints, "type", "value", SUMMARY_CONSTRAINTS_LIMIT
    )
    _append_summary_list(
        lines, "термины", state.fixed_terms, "term", "value", SUMMARY_TERMS_LIMIT
    )

    open_questions = [
        item
        for item in state.open_questions
        if item.get("status", "open") == "open" and item.get("question")
    ]
    if open_questions:
        questions = " | ".join(
            f"{item['question']} [{item.get('priority', 'medium')}]"
            for item in open_questions[:SUMMARY_QUESTIONS_LIMIT]
        )
        lines.append(f"- уточнить: {questions}")

    if state.last_user_intent:
        lines.append(f"- намерение пользователя: {state.last_user_intent}")
    lines.append(f"- ход диалога: {state.turn_count}")

    # Пустой state (extractor не отработал) не подмешивается в промт вовсе.
    has_content = bool(
        state.goal
        or state.confirmed_facts
        or state.constraints
        or state.fixed_terms
        or open_questions
        or state.last_user_intent
        or state.turn_count > 0
    )
    if not has_content:
        return ""

    summary = "\n".join(lines)
    # Гарантия лимита: если сводка превысила лимит — обрезаем списки жёстко.
    if estimate_tokens(summary) > STATE_SUMMARY_MAX_TOKENS:
        summary = "\n".join(lines[:3])  # цель + изменение цели + факты
        if estimate_tokens(summary) > STATE_SUMMARY_MAX_TOKENS:
            summary = f"Задача (Task State):\n- цель: {state.goal}"
    return summary


def _append_summary_list(
    lines: List[str],
    label: str,
    records: List[Dict[str, Any]],
    key_field: str,
    value_field: str,
    limit: int,
) -> None:
    """Добавляет строку сводки из актуальных записей (без superseded_by)."""
    active = [
        item
        for item in records
        if item.get("superseded_by") is None
        and item.get(key_field)
        and item.get(value_field)
    ][:limit]
    if not active:
        return
    rendered = "; ".join(f"{item[key_field]}: {item[value_field]}" for item in active)
    lines.append(f"- {label}: {rendered}")


# ---------------------------------------------------------------------------
# RAG: обогащение запроса goal + constraints + fixed_terms
# ---------------------------------------------------------------------------


def build_rag_query(user_text: str, state: TaskState, max_len: int = 600) -> str:
    """Формирует поисковый запрос к RAG, обогащённый состоянием задачи.

    Правило: запрос = вопрос пользователя + (если есть) формулировка цели
    + актуальные термины (до ~200 символов). Ограничивается ``max_len``,
    чтобы не раздувать эмбеддинг-запрос.
    """
    parts = [(user_text or "").strip()]
    if state.goal and state.goal not in (user_text or ""):
        parts.append(f"контекст задачи: {state.goal}")
    terms = [
        item.get("term")
        for item in state.fixed_terms
        if item.get("superseded_by") is None and item.get("term")
    ]
    if terms:
        parts.append("термины: " + ", ".join(terms[:5]))
    query = " ".join(part for part in parts if part)
    return query[:max_len]


# ---------------------------------------------------------------------------
# Guard: самопроверка ответа перед отправкой
# ---------------------------------------------------------------------------


# Явные типы ограничений, проверяемые детерминированно.
_LANGUAGE_CONSTRAINT_TYPES = {"language", "язык", "lang"}
_LENGTH_CONSTRAINT_TYPES = {"max_length", "длина", "максимальная_длина", "max_len"}


async def run_guards(
    answer: str,
    *,
    state: TaskState,
    rag_used: bool = False,
    sources: Optional[List[Dict[str, Any]]] = None,
    llm_checker: Optional[Callable[[str, TaskState], Any]] = None,
) -> List[str]:
    """Возвращает список проблем ответа (пустой список — ответ годен).

    Детерминированные проверки (всегда, явные правила):

    1. Если RAG был использован и есть чанки — ответ обязан содержать
       блок «Источники» и хотя бы один валидный ``source_id``/``url``
       из использованных чанков (маркер ``Источники`` + упоминание).
    2. Если задано ограничение языка — доля символов нужной письменности
       в ответе ≥ 0.5 (язык: "русский"/"ru" — кириллица, "english"/"en" —
       латиница).
    3. Если задано ограничение длины (максимум N символов) — не превышено.

    LLM-проверка (опционально, ``llm_checker``): соответствие цели и
    отсутствие противоречий с подтверждёнными фактами. Детерминированные
    эвристики в коде не используются — проверку выполняет модель с
    temperature=0 по явному промту.

    ``llm_checker`` — awaitable ``(answer, state) -> List[str]``.
    """
    problems: List[str] = []

    # 1. Источники.
    used_sources = [item for item in (sources or []) if item.get("source_id")]
    if rag_used and used_sources:
        mentioned = _sources_mentioned(answer, used_sources)
        if "Источники" not in answer:
            problems.append("нет блока «Источники» в ответе")
        if not mentioned:
            problems.append("в ответе нет ни одного source_id из использованных чанков")

    # 2. Язык.
    language = _active_constraint_value(state, _LANGUAGE_CONSTRAINT_TYPES)
    if language:
        language_lower = language.lower()
        ratio = _script_ratio(answer)
        latin_ratio, cyrillic_ratio = ratio
        if language_lower in ("русский", "ru", "russian") and cyrillic_ratio < 0.5:
            problems.append(f"ответ не на русском языке (ограничение: {language})")
        elif language_lower in ("english", "en", "английский") and latin_ratio < 0.5:
            problems.append(f"ответ не на английском языке (ограничение: {language})")

    # 3. Длина.
    length_value = _active_constraint_value(state, _LENGTH_CONSTRAINT_TYPES)
    max_length = _parse_max_length(length_value)
    if max_length and len(answer) > max_length:
        problems.append(
            f"ответ длиннее ограничения: {len(answer)} > {max_length} символов"
        )

    # 4. LLM-самопроверка (цель/факты).
    if llm_checker:
        try:
            problems.extend((await llm_checker(answer, state)) or [])
        except Exception:  # noqa: BLE001 - checker не должен ронять ответ
            pass
    return problems


def _active_constraint_value(state: TaskState, types: set) -> str:
    """Значение актуального ограничения заданного типа (или пустая строка)."""
    for item in state.constraints:
        if item.get("superseded_by") is None:
            raw_type = str(item.get("type", "") or "").strip().lower()
            if raw_type in types:
                value = str(item.get("value", "") or "").strip()
                if value:
                    return value
    return ""


def _parse_max_length(value: str) -> Optional[int]:
    """Извлекает число из значения ограничения длины («не более 1000 символов»)."""
    match = re.search(r"\d+", value or "")
    return int(match.group(0)) if match else None


def _script_ratio(text: str) -> tuple:
    """Возвращает (доля латиницы, доля кириллицы) среди букв ответа."""
    if not text:
        return 0.0, 0.0
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0, 0.0
    latin = sum(1 for ch in letters if ord("a") <= ord(ch.lower()) <= ord("z"))
    cyrillic = sum(1 for ch in letters if "\u0400" <= ch <= "\u04FF")
    return latin / len(letters), cyrillic / len(letters)


def _sources_mentioned(answer: str, sources: List[Dict[str, Any]]) -> bool:
    """True, если в ответе упомянут source_id или url хотя бы одного чанка."""
    lowered = (answer or "").lower()
    for source in sources:
        source_id = str(source.get("source_id", "") or "").strip()
        url = str(source.get("url", "") or "").strip()
        if source_id and source_id in lowered:
            return True
        if url and url.lower() in lowered:
            return True
    return False


def guard_retry_instruction(problems: List[str]) -> str:
    """Инструкция для повторной генерации при провале самопроверки.

    Проблемы передаются модели явно; ответ должен быть переформулирован
    с их учётом (это единственное «магическое» место — правила заданы ТЗ:
    retry с указанием проблемы в промте).
    """
    bullet = "\n".join(f"- {problem}" for problem in problems)
    return (
        "Самопроверка перед отправкой ответа не пройдена. Проблемы:\n"
        f"{bullet}\n"
        "Переформулируй ответ так, чтобы все проблемы были устранены: "
        "подтверди цель задачи, приведи блок «Источники» с реальными "
        "source_id из контекста, соблюди ограничения, не противоречь "
        "подтверждённым фактам."
    )


# ---------------------------------------------------------------------------
# Движок: связывает INIT/UPDATE/INJECT/PERSIST в один класс
# ---------------------------------------------------------------------------


class TaskStateEngine:
    """Оркестратор Task State для одного чата.

    ``llm_json`` — awaitable callable ``(messages) -> dict``, вызывающий
    модель с temperature=0 и JSON-режимом. В проде это обёртка над
    ``api_client.complete_json``, в тестах — детерминированный фейк без сети.
    """

    def __init__(
        self,
        chat_id: str,
        llm_json: Callable[[List[Dict[str, str]]], Any],
        store: Optional[TaskStateStore] = None,
    ) -> None:
        self.chat_id = chat_id
        self.llm_json = llm_json
        self.store = store or TaskStateStore()
        self.state = self.store.load(chat_id)

    # --- INIT/UPDATE ---

    async def update_from_user(
        self,
        user_text: str,
        msg_id: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> TaskState:
        """Извлекает обновление и применяет MERGE (INIT при первом сообщении)."""
        messages = build_extractor_messages(user_text, self.state, history)
        raw = await self.llm_json(messages)
        self.state.merge_extraction(
            normalize_extraction(raw), source_msg_id=msg_id, ts=_now()
        )
        self.persist()
        return self.state

    # --- INJECT ---

    def build_summary(self) -> str:
        """Компактная сводка для подмешивания в system-промт."""
        return build_state_summary(self.state)

    # --- PERSIST ---

    def persist(self) -> bool:
        """Сохраняет state на диск."""
        return self.store.save(self.state)

    # --- после ответа ассистента ---

    def record_answer(
        self,
        answer: str,
        sources: Optional[List[Dict[str, Any]]] = None,
        msg_id: str = "",
    ) -> TaskState:
        """Локальное обновление state по итогам ответа (источники, ход)."""
        self.state.record_assistant_turn(answer, sources, msg_id)
        self.persist()
        return self.state