"""Data access layer for working and long-term memory.

Short-term memory is the ``messages`` table and lives in
:mod:`backend.database.repositories`; the two layers below have their own
tables because their shape and lifetime differ.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from backend.database.database import Database, get_database
from backend.memory.models import (
    LongTermEntry,
    MemoryCategory,
    WorkingMemoryData,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class WorkingMemoryRepository:
    """Stores the structured task state of a single chat."""

    def __init__(self, database: Optional[Database] = None) -> None:
        self._db = database or get_database()

    def get(self, chat_id: str) -> Optional[WorkingMemoryData]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT data FROM working_memory WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            return WorkingMemoryData()
        if not isinstance(payload, dict):
            return WorkingMemoryData()
        return WorkingMemoryData(**payload)

    def get_updated_at(self, chat_id: str) -> Optional[datetime]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT updated_at FROM working_memory WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return _parse(row["updated_at"]) if row else None

    def save(self, chat_id: str, data: WorkingMemoryData) -> datetime:
        now = utcnow()
        payload = json.dumps(data.model_dump(), ensure_ascii=False)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO working_memory (chat_id, data, updated_at)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT(chat_id) DO UPDATE SET"
                " data = excluded.data, updated_at = excluded.updated_at",
                (chat_id, payload, _iso(now)),
            )
        return now

    def delete(self, chat_id: str) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM working_memory WHERE chat_id = ?", (chat_id,)
            )
            return cursor.rowcount > 0


class LongTermMemoryRepository:
    """Stores durable facts about the user, shared between chats."""

    def __init__(self, database: Optional[Database] = None) -> None:
        self._db = database or get_database()

    def list(self) -> List[LongTermEntry]:
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                "SELECT id, category, key, value, source, confidence,"
                " created_at, updated_at FROM long_term_memory"
                " ORDER BY category ASC, key ASC"
            ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get(self, memory_id: str) -> Optional[LongTermEntry]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT id, category, key, value, source, confidence,"
                " created_at, updated_at FROM long_term_memory WHERE id = ?",
                (memory_id,),
            ).fetchone()
        return self._row_to_entry(row) if row else None

    def find_by_key(self, category: str, key: str) -> Optional[LongTermEntry]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT id, category, key, value, source, confidence,"
                " created_at, updated_at FROM long_term_memory"
                " WHERE category = ? AND key = ?",
                (category, key),
            ).fetchone()
        return self._row_to_entry(row) if row else None

    def upsert(
        self,
        *,
        category: MemoryCategory,
        key: str,
        value: str,
        source: str = "manual",
        confidence: float = 1.0,
    ) -> LongTermEntry:
        """Insert a fact, or update the value of an existing (category, key)."""
        existing = self.find_by_key(category, key)
        now = utcnow()
        if existing is not None:
            with self._db.transaction() as conn:
                conn.execute(
                    "UPDATE long_term_memory SET value = ?, source = ?,"
                    " confidence = ?, updated_at = ? WHERE id = ?",
                    (value, source, confidence, _iso(now), existing.id),
                )
            updated = self.get(existing.id)
            assert updated is not None
            return updated

        memory_id = str(uuid.uuid4())
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO long_term_memory"
                " (id, category, key, value, source, confidence, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory_id,
                    category,
                    key,
                    value,
                    source,
                    confidence,
                    _iso(now),
                    _iso(now),
                ),
            )
        created = self.get(memory_id)
        assert created is not None
        return created

    def update(
        self,
        memory_id: str,
        *,
        category: Optional[str] = None,
        key: Optional[str] = None,
        value: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> Optional[LongTermEntry]:
        fields: List[str] = []
        params: List[object] = []
        if category is not None:
            fields.append("category = ?")
            params.append(category)
        if key is not None:
            fields.append("key = ?")
            params.append(key)
        if value is not None:
            fields.append("value = ?")
            params.append(value)
        if confidence is not None:
            fields.append("confidence = ?")
            params.append(confidence)
        if not fields:
            return self.get(memory_id)

        fields.append("updated_at = ?")
        params.append(_iso(utcnow()))
        params.append(memory_id)
        with self._db.transaction() as conn:
            cursor = conn.execute(
                f"UPDATE long_term_memory SET {', '.join(fields)} WHERE id = ?",
                params,
            )
            if cursor.rowcount == 0:
                return None
        return self.get(memory_id)

    def delete(self, memory_id: str) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM long_term_memory WHERE id = ?", (memory_id,)
            )
            return cursor.rowcount > 0

    def clear(self) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute("DELETE FROM long_term_memory")
            return cursor.rowcount

    @staticmethod
    def _row_to_entry(row) -> LongTermEntry:
        return LongTermEntry(
            id=row["id"],
            category=row["category"],
            key=row["key"],
            value=row["value"],
            source=row["source"],
            confidence=float(row["confidence"]),
            created_at=_parse(row["created_at"]),
            updated_at=_parse(row["updated_at"]),
        )