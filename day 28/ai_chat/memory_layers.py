"""Трёхслойная память агента: short-term, working и long-term.

Модуль реализует три независимых слоя памяти и единый фасад ``MemoryManager``:

* :class:`ShortTermMemory` — последние сообщения диалога (in-memory, FIFO);
* :class:`WorkingMemory` — структурированное состояние текущей задачи (in-memory);
* :class:`LongTermMemory` — устойчивые факты о пользователе (SQLite, между сессиями).

Запись в слой выполняет явный роутер :func:`decide_where_to_store`, а сборка
контекста для LLM — :meth:`MemoryManager.build_prompt_messages`.

Модуль не зависит от FastAPI и может использоваться как библиотека
(см. ``demo_memory.py``).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LONG_TERM_DB_PATH = os.path.join(BASE_DIR, "memory.db")

# Лимиты short-term памяти.
SHORT_TERM_MAX_MESSAGES = 20
SHORT_TERM_MAX_TOKENS = 2000

# Слои памяти.
LAYER_SHORT = "short"
LAYER_WORKING = "working"
LAYER_LONG = "long"
LAYERS = (LAYER_SHORT, LAYER_WORKING, LAYER_LONG)

# Ключи рабочей памяти, которые считаются «полями задачи».
WORKING_FIELDS = ("goal", "constraints", "results", "status", "todo")


def _now() -> str:
    """Текущее время в формате ISO-8601 (UTC)."""
    return datetime.now(timezone.utc).isoformat()


def estimate_tokens(text: str) -> int:
    """Грубая оценка числа токенов: ~4 символа на токен (как у OpenAI)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Слой 1. Краткосрочная память
# ---------------------------------------------------------------------------


@dataclass
class ShortTermMemory:
    """Краткосрочная память: последние сообщения текущего диалога.

    Хранится в памяти процесса, ключ — ``session_id``. Политика FIFO:
    при превышении лимита по количеству сообщений или по токенам самые
    старые сообщения вытесняются.
    """

    max_messages: int = SHORT_TERM_MAX_MESSAGES
    max_tokens: int = SHORT_TERM_MAX_TOKENS
    _sessions: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def add(self, session_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """Добавляет сообщение (``role`` + ``content`` + ``timestamp``) в сессию."""
        entry = {
            "role": message.get("role", "user"),
            "content": message.get("content", ""),
            "timestamp": message.get("timestamp") or _now(),
        }
        with self._lock:
            history = self._sessions.setdefault(session_id, [])
            history.append(entry)
            self._trim(history)
        return entry

    def read(self, session_id: str) -> List[Dict[str, Any]]:
        """Возвращает копию списка сообщений сессии (от старых к новым)."""
        with self._lock:
            return [dict(item) for item in self._sessions.get(session_id, [])]

    def clear(self, session_id: str) -> None:
        """Полностью очищает краткосрочную память сессии."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def _trim(self, history: List[Dict[str, Any]]) -> None:
        """Вытесняет старые сообщения по лимитам количества и токенов (FIFO)."""
        while len(history) > self.max_messages:
            history.pop(0)
        while len(history) > 1 and self._total_tokens(history) > self.max_tokens:
            history.pop(0)

    @staticmethod
    def _total_tokens(history: List[Dict[str, Any]]) -> int:
        """Суммарная оценка токенов по всем сообщениям истории."""
        return sum(estimate_tokens(item.get("content", "")) for item in history)


# ---------------------------------------------------------------------------
# Слой 2. Рабочая память
# ---------------------------------------------------------------------------


@dataclass
class WorkingMemory:
    """Рабочая память: структурированное состояние текущей задачи.

    Хранится в памяти процесса, ключ — ``session_id``. Живёт, пока задача
    активна; при завершении может быть очищена или «схлопнута» в long-term
    (см. :meth:`MemoryManager.collapse_working`).
    """

    _sessions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def update(self, session_id: str, key: str, value: Any) -> Dict[str, Any]:
        """Записывает значение по ключу задачи, создавая сессию при необходимости."""
        with self._lock:
            state = self._sessions.setdefault(session_id, self._empty_state())
            if key in ("constraints", "results", "todo"):
                items = state.setdefault(key, [])
                if isinstance(value, list):
                    items.extend(value)
                else:
                    items.append(value)
            else:
                state[key] = value
            state["updated_at"] = _now()
            return dict(state)

    def read(self, session_id: str) -> Dict[str, Any]:
        """Возвращает копию состояния задачи для сессии."""
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return self._empty_state()
            return json.loads(json.dumps(state, ensure_ascii=False))

    def clear(self, session_id: str) -> None:
        """Очищает рабочую память сессии (задача завершена)."""
        with self._lock:
            self._sessions.pop(session_id, None)

    @staticmethod
    def _empty_state() -> Dict[str, Any]:
        """Пустое состояние задачи со всеми полями."""
        return {
            "goal": "",
            "constraints": [],
            "results": [],
            "status": "active",
            "todo": [],
            "updated_at": _now(),
        }


# ---------------------------------------------------------------------------
# Слой 3. Долговременная память
# ---------------------------------------------------------------------------


class LongTermMemory:
    """Долговременная память: устойчивые факты о пользователе (SQLite).

    Сохраняется между сессиями, доступ по ``user_id``. Каждый факт имеет
    счётчик подтверждений ``confirmations``: повторная запись того же факта
    увеличивает счётчик, а не создаёт дубликат.
    """

    def __init__(self, db_path: str = LONG_TERM_DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Открывает соединение с БД (создавая каталог при необходимости)."""
        directory = os.path.dirname(os.path.abspath(self.db_path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        """Создаёт таблицу фактов, если её ещё нет."""
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    source TEXT NOT NULL DEFAULT 'router',
                    confirmations INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_user ON facts(user_id)"
            )

    def save(
        self,
        user_id: str,
        fact: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Сохраняет факт, увеличивая счётчик подтверждений при повторе."""
        metadata = metadata or {}
        category = str(metadata.get("category", "general"))
        source = str(metadata.get("source", "router"))
        normalized = " ".join((fact or "").split())
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM facts WHERE user_id = ? AND fact = ?",
                (user_id, normalized),
            ).fetchone()
            if row is not None:
                confirmations = int(row["confirmations"]) + 1
                connection.execute(
                    "UPDATE facts SET confirmations = ?, updated_at = ? WHERE id = ?",
                    (confirmations, _now(), row["id"]),
                )
                return {
                    "id": row["id"],
                    "user_id": user_id,
                    "fact": normalized,
                    "category": row["category"],
                    "source": row["source"],
                    "confirmations": confirmations,
                    "created_at": row["created_at"],
                    "updated_at": _now(),
                }
            fact_id = str(uuid.uuid4())
            created = _now()
            connection.execute(
                """
                INSERT INTO facts
                    (id, user_id, fact, category, source, confirmations, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (fact_id, user_id, normalized, category, source, created, created),
            )
            return {
                "id": fact_id,
                "user_id": user_id,
                "fact": normalized,
                "category": category,
                "source": source,
                "confirmations": 1,
                "created_at": created,
                "updated_at": created,
            }

    def read(self, user_id: str) -> List[Dict[str, Any]]:
        """Возвращает все факты пользователя (сначала самые свежие)."""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM facts WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def search(self, user_id: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Возвращает top-k фактов, релевантных запросу (по пересечению слов).

        Если ни один факт не пересекается с запросом, возвращаются самые
        свежие факты — профиль пользователя полезен и без явного совпадения.
        """
        facts = self.read(user_id)
        if not query or not query.strip():
            return facts[:top_k]
        query_words = _words(query)
        scored: List[Tuple[int, Dict[str, Any]]] = []
        for fact in facts:
            overlap = len(query_words & _words(fact.get("fact", "")))
            if overlap:
                scored.append((overlap, fact))
        if not scored:
            return facts[:top_k]
        scored.sort(key=lambda item: (-item[0], item[1].get("updated_at", "")))
        return [fact for _, fact in scored[:top_k]]

    def delete(self, fact_id: str) -> bool:
        """Удаляет факт по идентификатору. Возвращает ``True``, если он был удалён."""
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            return cursor.rowcount > 0

    def clear(self, user_id: str) -> None:
        """Удаляет все факты пользователя."""
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM facts WHERE user_id = ?", (user_id,))


def _words(text: str) -> set:
    """Множество значимых слов строки (для оценки релевантности)."""
    return {word for word in re.findall(r"[\w\-]+", (text or "").lower()) if len(word) > 2}


# ---------------------------------------------------------------------------
# Роутер записи
# ---------------------------------------------------------------------------

# Явные маркеры устойчивого предпочтения.
_PREFERENCE_MARKERS = (
    "предпочитаю",
    "предпочитает",
    "мне нравится",
    "мне не нравится",
    "я люблю",
    "я не люблю",
    "я всегда",
    "я никогда",
    "я обычно",
    "обращайся ко мне",
    "зови меня",
    "называй меня",
    "мой стиль",
    "моё имя",
    "мое имя",
    "меня зовут",
    "я работаю",
    "я живу",
    "я использую",
    "запомни",
    "запомни, что",
    "всегда отвечай",
    "не используй",
    "отвечай мне",
)

# Маркеры задачи (рабочая память).
_TASK_MARKERS = (
    "цель",
    "задача",
    "нужно сделать",
    "надо сделать",
    "план",
    "todo",
    "шаг",
    "ограничение",
    "дедлайн",
    "статус",
    "промежуточный результат",
    "сделай",
    "помоги сделать",
    "реализуй",
    "напиши код",
    "исправь",
    "настрой",
    "забронируй",
    "забронировать",
    "бронируй",
    "подбери",
    "найди",
    "выбери",
    "оформи",
    "купи",
    "закажи",
    "отправь",
    "составь",
    "подготовь",
)

# Маркеры завершения задачи.
_COMPLETION_MARKERS = (
    "готово",
    "задача выполнена",
    "завершено",
    "всё сделано",
    "все сделано",
    "спасибо, всё",
    "спасибо, все",
    "на этом всё",
    "на этом все",
)


@dataclass
class RoutingDecision:
    """Решение роутера: в какой слой писать факт и почему."""

    layer: str
    reason: str
    category: str = "general"
    key: Optional[str] = None
    value: Any = None

    def to_dict(self) -> Dict[str, Any]:
        """Представление решения для логов и API."""
        return {
            "layer": self.layer,
            "reason": self.reason,
            "category": self.category,
            "key": self.key,
            "value": self.value,
        }


def decide_where_to_store(
    fact: str,
    *,
    confirmations: int = 1,
    explicit: bool = False,
    is_task: bool = False,
) -> RoutingDecision:
    """Решает, в какой слой памяти писать факт, и объясняет решение.

    Правила (по приоритету):

    1. Явное предпочтение пользователя (маркеры «предпочитаю», «запомни»,
       «меня зовут» и т. п.) **или** факт, подтверждённый ≥2 раз, → ``long``.
    2. Факт относится к текущей задаче (маркеры цели/плана/ограничений) → ``working``.
    3. Всё остальное — реплика диалога → ``short``.

    :param fact: текст факта или реплики.
    :param confirmations: сколько раз факт уже встречался.
    :param explicit: пометка «пользователь явно попросил запомнить».
    :param is_task: пометка «факт относится к задаче».
    :returns: :class:`RoutingDecision` с обоснованием.
    """
    text = (fact or "").strip()
    lowered = text.lower()

    if not text:
        return RoutingDecision(LAYER_SHORT, "Пустой текст — писать нечего.", "general")

    preference_hit = next((m for m in _PREFERENCE_MARKERS if m in lowered), None)
    if explicit or preference_hit:
        reason = (
            "Пользователь явно попросил запомнить."
            if explicit
            else f"Явное устойчивое предпочтение (маркер «{preference_hit}»)."
        )
        return RoutingDecision(LAYER_LONG, reason, "preference", value=text)

    if confirmations >= 2:
        return RoutingDecision(
            LAYER_LONG,
            f"Факт подтверждён {confirmations} раза — считается устойчивым.",
            "confirmed",
            value=text,
        )

    task_hit = next((m for m in _TASK_MARKERS if m in lowered), None)
    if is_task or task_hit:
        key = _guess_working_key(lowered)
        reason = (
            "Факт помечен как относящийся к задаче."
            if is_task
            else f"Факт относится к текущей задаче (маркер «{task_hit}»)."
        )
        return RoutingDecision(LAYER_WORKING, reason, "task", key=key, value=text)

    return RoutingDecision(
        LAYER_SHORT,
        "Обычная реплика диалога — хранится в краткосрочной памяти.",
        "dialogue",
        value=text,
    )


def _guess_working_key(lowered: str) -> str:
    """Подбирает поле рабочей памяти по тексту факта."""
    if any(marker in lowered for marker in ("цель", "задача", "нужно сделать", "надо сделать")):
        return "goal"
    if any(marker in lowered for marker in ("ограничение", "дедлайн", "нельзя", "только")):
        return "constraints"
    if any(marker in lowered for marker in ("todo", "план", "шаг", "список дел")):
        return "todo"
    if any(marker in lowered for marker in ("статус", "готово", "в процессе")):
        return "status"
    return "results"


def extract_working_fields(text: str) -> Dict[str, Any]:
    """Извлекает структурированные поля задачи из реплики.

    Понимает простые шаблоны: город («в Берлине»), даты («на 12-15 мая»),
    а также явные пометки цели/ограничений. Возвращает словарь полей
    рабочей памяти (может быть пустым).
    """
    lowered = (text or "").lower()
    fields: Dict[str, Any] = {}

    city = re.search(r"\bв\s+([А-ЯЁA-Z][\w\-]+)", text or "")
    if city:
        fields["city"] = city.group(1)

    dates = re.search(r"\bна\s+([\d]{1,2}\s*[-–]\s*[\d]{1,2}\s+[а-яё]+)", lowered)
    if not dates:
        dates = re.search(r"\bна\s+([\d]{1,2}\s+[а-яё]+)", lowered)
    if dates:
        fields["dates"] = dates.group(1).strip()

    if any(marker in lowered for marker in _TASK_MARKERS):
        fields["task"] = text.strip()

    return fields


def is_task_completed(text: str) -> bool:
    """Проверяет, сообщает ли пользователь о завершении задачи."""
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _COMPLETION_MARKERS)


# ---------------------------------------------------------------------------
# Журнал событий маршрутизации
# ---------------------------------------------------------------------------


class MemoryEventLog:
    """In-memory журнал событий записи в слои памяти.

    Каждый вызов ``add_short_term`` / ``update_working`` / ``save_long_term``
    добавляет сюда событие, чтобы на дашборде было видно, кто и куда записал.
    Журнал ограничен по длине (FIFO) и не сохраняется между перезапусками.
    """

    def __init__(self, max_events: int = 200) -> None:
        self.max_events = max_events
        self._events: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

    def add(
        self,
        layer: str,
        action: str,
        *,
        key: Optional[str] = None,
        value: Any = None,
        reason: str = "",
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Добавляет событие маршрутизации и возвращает его."""
        event = {
            "ts": _now(),
            "layer": layer,
            "action": action,
            "key": key,
            "value": value,
            "reason": reason,
            "session_id": session_id,
            "user_id": user_id,
        }
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.max_events:
                del self._events[: len(self._events) - self.max_events]
        return event

    def read(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Возвращает последние события (сначала новые)."""
        with self._lock:
            items = list(self._events)
        items.reverse()
        return items[:limit]

    def clear(self) -> None:
        """Очищает журнал событий."""
        with self._lock:
            self._events.clear()


# ---------------------------------------------------------------------------
# Фасад MemoryManager
# ---------------------------------------------------------------------------


class MemoryManager:
    """Единый интерфейс доступа ко всем трём слоям памяти.

    Слои можно отключать (ablation): отключённый слой не читается при сборке
    промта и не пополняется при записи.
    """

    def __init__(
        self,
        short_term: Optional[ShortTermMemory] = None,
        working: Optional[WorkingMemory] = None,
        long_term: Optional[LongTermMemory] = None,
        enabled_layers: Optional[List[str]] = None,
    ) -> None:
        self.short_term = short_term or ShortTermMemory()
        self.working = working or WorkingMemory()
        self.long_term = long_term or LongTermMemory()
        self.enabled_layers = set(enabled_layers or LAYERS)
        self.events = MemoryEventLog()
        self._log: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

    # --- Чтение -----------------------------------------------------------

    def read_short_term(self, session_id: str) -> List[Dict[str, Any]]:
        """Читает краткосрочную память сессии."""
        if LAYER_SHORT not in self.enabled_layers:
            return []
        return self.short_term.read(session_id)

    def read_working(self, session_id: str) -> Dict[str, Any]:
        """Читает рабочую память сессии."""
        if LAYER_WORKING not in self.enabled_layers:
            return WorkingMemory._empty_state()
        return self.working.read(session_id)

    def read_long_term(self, user_id: str) -> List[Dict[str, Any]]:
        """Читает долговременную память пользователя."""
        if LAYER_LONG not in self.enabled_layers:
            return []
        return self.long_term.read(user_id)

    # --- Запись -----------------------------------------------------------

    def add_short_term(self, session_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """Добавляет сообщение в краткосрочную память."""
        if LAYER_SHORT not in self.enabled_layers:
            return {}
        entry = self.short_term.add(session_id, message)
        self.events.add(
            LAYER_SHORT,
            "add",
            key=entry.get("role"),
            value=entry.get("content", "")[:120],
            reason="сообщение диалога",
            session_id=session_id,
        )
        return entry

    def update_working(self, session_id: str, key: str, value: Any) -> Dict[str, Any]:
        """Обновляет поле рабочей памяти."""
        if LAYER_WORKING not in self.enabled_layers:
            return {}
        state = self.working.update(session_id, key, value)
        self.events.add(
            LAYER_WORKING,
            "update",
            key=key,
            value=value,
            reason="данные задачи",
            session_id=session_id,
        )
        return state

    def save_long_term(
        self,
        user_id: str,
        fact: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Сохраняет устойчивый факт в долговременную память."""
        if LAYER_LONG not in self.enabled_layers:
            return {}
        saved = self.long_term.save(user_id, fact, metadata)
        self.events.add(
            LAYER_LONG,
            "save",
            key=(metadata or {}).get("category", "general"),
            value=fact,
            reason=(metadata or {}).get("source", "router"),
            user_id=user_id,
        )
        return saved

    # --- Роутер и запись «по решению» -------------------------------------

    def route_and_store(
        self,
        session_id: str,
        user_id: str,
        fact: str,
        *,
        confirmations: int = 1,
        explicit: bool = False,
        is_task: bool = False,
    ) -> RoutingDecision:
        """Определяет слой через роутер и записывает факт в него.

        Для слоя ``short`` запись не выполняется: реплики диалога добавляет
        вызывающий код через :meth:`add_short_term` (чтобы не дублировать их).
        """
        decision = decide_where_to_store(
            fact, confirmations=confirmations, explicit=explicit, is_task=is_task
        )
        if decision.layer == LAYER_LONG:
            self.save_long_term(
                user_id,
                fact,
                {"category": decision.category, "source": "router"},
            )
        elif decision.layer == LAYER_WORKING:
            # Пишем и общее поле (goal/results/...), и структурированные поля задачи.
            self.update_working(session_id, decision.key or "results", fact)
            for key, value in extract_working_fields(fact).items():
                if key == "task":
                    continue
                self.update_working(session_id, key, value)
        return decision

    def collapse_working(self, session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """«Схлопывает» завершённую задачу в long-term и очищает рабочую память.

        В долговременную память попадает только итог задачи (цель + результаты).
        """
        state = self.working.read(session_id)
        goal = state.get("goal") or ""
        results = state.get("results") or []
        if not goal and not results:
            self.working.clear(session_id)
            return None
        summary_parts = [part for part in [goal, *results] if part]
        summary = "Итог задачи: " + "; ".join(str(part) for part in summary_parts)
        saved = self.save_long_term(
            user_id, summary, {"category": "task_summary", "source": "collapse"}
        )
        self.working.clear(session_id)
        return saved or None

    # --- Сборка промта ----------------------------------------------------

    def build_prompt_messages(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        *,
        system_prompt: Optional[str] = None,
        long_term_top_k: int = 5,
    ) -> List[Dict[str, str]]:
        """Собирает контекст для LLM: system + long-term + working + short-term.

        :param session_id: идентификатор сессии (чат).
        :param user_id: идентификатор пользователя (для long-term).
        :param user_message: текущее сообщение пользователя.
        :param system_prompt: базовый системный промт (если нужен).
        :param long_term_top_k: сколько релевантных фактов брать из long-term.
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        long_facts = self.long_term.search(user_id, user_message, top_k=long_term_top_k) \
            if LAYER_LONG in self.enabled_layers else []
        if long_facts:
            lines = [f"- {fact['fact']}" for fact in long_facts]
            messages.append(
                {
                    "role": "system",
                    "content": "Долговременная память о пользователе:\n" + "\n".join(lines),
                }
            )

        working = self.read_working(session_id)
        working_text = self._format_working(working)
        if working_text:
            messages.append(
                {"role": "system", "content": "Текущая задача:\n" + working_text}
            )

        for item in self.read_short_term(session_id):
            messages.append({"role": item["role"], "content": item["content"]})

        messages.append({"role": "user", "content": user_message})
        return messages

    @staticmethod
    def _format_working(state: Dict[str, Any]) -> str:
        """Форматирует рабочую память в текст для системного сообщения."""
        lines: List[str] = []
        if state.get("goal"):
            lines.append(f"Цель: {state['goal']}")
        if state.get("constraints"):
            lines.append("Ограничения: " + "; ".join(map(str, state["constraints"])))
        if state.get("todo"):
            lines.append("План: " + "; ".join(map(str, state["todo"])))
        if state.get("results"):
            lines.append("Промежуточные результаты: " + "; ".join(map(str, state["results"])))
        if state.get("status") and state["status"] != "active":
            lines.append(f"Статус: {state['status']}")
        # Произвольные ключи задачи (например, city, dates) тоже попадают в промт.
        known = {"goal", "constraints", "todo", "results", "status", "updated_at"}
        for key, value in state.items():
            if key in known or not value:
                continue
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    # --- Логи и диагностика ----------------------------------------------

    def log_step(self, step: str, decision: Optional[RoutingDecision] = None) -> Dict[str, Any]:
        """Фиксирует шаг обработки и решение роутера (для демонстрации)."""
        entry = {
            "step": step,
            "timestamp": _now(),
            "decision": decision.to_dict() if decision else None,
        }
        with self._lock:
            self._log.append(entry)
        return entry

    def get_log(self) -> List[Dict[str, Any]]:
        """Возвращает накопленный журнал шагов."""
        with self._lock:
            return [dict(item) for item in self._log]

    def snapshot(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """Снимок содержимого всех слоёв — для логов, API и демо-скрипта."""
        return {
            "short_term": self.read_short_term(session_id),
            "working": self.read_working(session_id),
            "long_term": self.read_long_term(user_id),
            "enabled_layers": sorted(self.enabled_layers),
        }

    def set_enabled_layers(self, layers: List[str]) -> None:
        """Включает только указанные слои (для ablation-эксперимента)."""
        self.enabled_layers = {layer for layer in layers if layer in LAYERS}

    def delete_long_term(self, fact_id: str) -> bool:
        """Удаляет факт из долговременной памяти по идентификатору."""
        deleted = self.long_term.delete(fact_id)
        if deleted:
            self.events.add(
                LAYER_LONG,
                "delete",
                key=fact_id,
                reason="факт удалён вручную",
            )
        return deleted

    def prompt_preview(
        self,
        session_id: str,
        user_id: str,
        user_message: str = "",
        *,
        long_term_top_k: int = 5,
    ) -> Dict[str, Any]:
        """Возвращает собранный промт с разметкой, из какого слоя пришёл блок.

        Используется дашбордом: показывает, как три слоя склеиваются в контекст.
        """
        messages = self.build_prompt_messages(
            session_id, user_id, user_message, long_term_top_k=long_term_top_k
        )
        blocks: List[Dict[str, Any]] = []
        for index, message in enumerate(messages):
            role = message.get("role", "")
            content = message.get("content", "")
            if role == "system" and content.startswith("Долговременная память"):
                source = LAYER_LONG
            elif role == "system" and content.startswith("Текущая задача"):
                source = LAYER_WORKING
            elif role == "system":
                source = "system"
            elif index == len(messages) - 1:
                source = "current"
            else:
                source = LAYER_SHORT
            blocks.append({"role": role, "source": source, "content": content})
        return {
            "messages": messages,
            "blocks": blocks,
            "text": self._render_prompt_text(blocks),
            "enabled_layers": sorted(self.enabled_layers),
        }

    @staticmethod
    def _render_prompt_text(blocks: List[Dict[str, Any]]) -> str:
        """Собирает промт в одну строку с пометками источника каждого блока."""
        parts: List[str] = []
        for block in blocks:
            parts.append(f"### [{block['source']}] {block['role']}\n{block['content']}")
        return "\n\n".join(parts)


# Глобальный экземпляр для веб-приложения.
memory_manager = MemoryManager()
