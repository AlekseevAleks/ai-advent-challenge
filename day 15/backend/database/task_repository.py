"""Data access layer for task states.

One row per task, keyed by ``task_id``. The structured columns (``stage``,
``current_step``, ``expected_action``, ``status``) are duplicated out of the
JSON blob so they can be queried and indexed directly, while ``data`` keeps the
full state (including history and metadata).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from backend.database.database import Database, get_database
from backend.tasks.models import TaskStateData


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class TaskStateRepository:
    """CRUD for task states."""

    def __init__(self, database: Optional[Database] = None) -> None:
        self._db = database or get_database()

    # ------------------------------------------------------------------ read
    def get(self, task_id: str) -> Optional[TaskStateData]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT data FROM task_states WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            return TaskStateData()
        if not isinstance(payload, dict):
            return TaskStateData()
        return TaskStateData(**payload)

    def get_meta(
        self, task_id: str
    ) -> Optional[Tuple[str, datetime, datetime]]:
        """Return ``(chat_id, created_at, updated_at)`` or ``None``."""
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT chat_id, created_at, updated_at FROM task_states"
                " WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return row["chat_id"], _parse(row["created_at"]), _parse(row["updated_at"])

    def exists(self, task_id: str) -> bool:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT 1 FROM task_states WHERE task_id = ?", (task_id,)
            ).fetchone()
        return row is not None

    def list_for_chat(self, chat_id: str) -> List[str]:
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                "SELECT task_id FROM task_states WHERE chat_id = ?"
                " ORDER BY created_at ASC",
                (chat_id,),
            ).fetchall()
        return [row["task_id"] for row in rows]

    def count(self) -> int:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT COUNT(*) AS total FROM task_states"
            ).fetchone()
        return int(row["total"]) if row else 0

    # ----------------------------------------------------------------- write
    def save(
        self, task_id: str, chat_id: str, data: TaskStateData
    ) -> Tuple[datetime, datetime]:
        """Insert or update one task state. Returns ``(created, updated)``."""
        now = utcnow()
        payload = json.dumps(data.model_dump(), ensure_ascii=False)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO task_states"
                " (task_id, chat_id, stage, current_step, expected_action,"
                "  status, data, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(task_id) DO UPDATE SET"
                " chat_id = excluded.chat_id,"
                " stage = excluded.stage,"
                " current_step = excluded.current_step,"
                " expected_action = excluded.expected_action,"
                " status = excluded.status,"
                " data = excluded.data,"
                " updated_at = excluded.updated_at",
                (
                    task_id,
                    chat_id,
                    data.stage,
                    data.current_step,
                    data.expected_action,
                    data.status,
                    payload,
                    _iso(now),
                    _iso(now),
                ),
            )
        meta = self.get_meta(task_id)
        if meta is None:  # pragma: no cover - defensive
            return now, now
        return meta[1], meta[2]

    def delete(self, task_id: str) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM task_states WHERE task_id = ?", (task_id,)
            )
            return cursor.rowcount > 0

    def delete_for_chat(self, chat_id: str) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM task_states WHERE chat_id = ?", (chat_id,)
            )
            return cursor.rowcount