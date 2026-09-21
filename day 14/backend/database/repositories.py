"""Data access layer for chats and messages."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from backend.database.database import Database, get_database
from backend.models.chat import Chat
from backend.models.message import Message, Role

DEFAULT_CHAT_TITLE = "Новый чат"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class ChatRepository:
    """CRUD operations for chats."""

    def __init__(self, database: Optional[Database] = None) -> None:
        self._db = database or get_database()

    def create(self, model: str, title: Optional[str] = None) -> Chat:
        chat_id = str(uuid.uuid4())
        now = utcnow()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO chats (id, title, model, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (chat_id, title or DEFAULT_CHAT_TITLE, model, _iso(now), _iso(now)),
            )
        return Chat(
            id=chat_id,
            title=title or DEFAULT_CHAT_TITLE,
            model=model,
            created_at=now,
            updated_at=now,
            message_count=0,
        )

    def list(self) -> List[Chat]:
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                """
                SELECT c.id, c.title, c.model, c.created_at, c.updated_at,
                       (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.id)
                           AS message_count
                FROM chats c
                ORDER BY c.updated_at DESC
                """
            ).fetchall()
        return [self._row_to_chat(row) for row in rows]

    def get(self, chat_id: str) -> Optional[Chat]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                """
                SELECT c.id, c.title, c.model, c.created_at, c.updated_at,
                       (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.id)
                           AS message_count
                FROM chats c
                WHERE c.id = ?
                """,
                (chat_id,),
            ).fetchone()
        return self._row_to_chat(row) if row else None

    def update(
        self,
        chat_id: str,
        *,
        title: Optional[str] = None,
        model: Optional[str] = None,
        touch: bool = True,
    ) -> Optional[Chat]:
        fields: List[str] = []
        params: List[object] = []
        if title is not None:
            fields.append("title = ?")
            params.append(title)
        if model is not None:
            fields.append("model = ?")
            params.append(model)
        if touch:
            fields.append("updated_at = ?")
            params.append(_iso(utcnow()))
        if not fields:
            return self.get(chat_id)

        params.append(chat_id)
        with self._db.transaction() as conn:
            cursor = conn.execute(
                f"UPDATE chats SET {', '.join(fields)} WHERE id = ?", params
            )
            if cursor.rowcount == 0:
                return None
        return self.get(chat_id)

    def touch(self, chat_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ?",
                (_iso(utcnow()), chat_id),
            )

    def delete(self, chat_id: str) -> bool:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            cursor = conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_chat(row) -> Chat:
        return Chat(
            id=row["id"],
            title=row["title"],
            model=row["model"],
            created_at=_parse(row["created_at"]),
            updated_at=_parse(row["updated_at"]),
            message_count=row["message_count"] if "message_count" in row.keys() else 0,
        )


class MessageRepository:
    """CRUD operations for messages."""

    def __init__(self, database: Optional[Database] = None) -> None:
        self._db = database or get_database()

    def add(self, chat_id: str, role: Role, content: str) -> Message:
        message_id = str(uuid.uuid4())
        now = utcnow()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO messages (id, chat_id, role, content, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (message_id, chat_id, role, content, _iso(now)),
            )
        return Message(
            id=message_id,
            chat_id=chat_id,
            role=role,
            content=content,
            created_at=now,
        )

    def list_for_chat(self, chat_id: str) -> List[Message]:
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                "SELECT id, chat_id, role, content, created_at FROM messages"
                " WHERE chat_id = ? ORDER BY created_at ASC, rowid ASC",
                (chat_id,),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def count_for_chat(self, chat_id: str) -> int:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT COUNT(*) AS total FROM messages WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return int(row["total"]) if row else 0

    def delete(self, message_id: str) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            return cursor.rowcount > 0

    def delete_last_assistant(self, chat_id: str) -> bool:
        """Remove the most recent assistant message of a chat."""
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM messages WHERE chat_id = ? AND role = 'assistant'"
                " ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM messages WHERE id = ?", (row["id"],))
            return True

    @staticmethod
    def _row_to_message(row) -> Message:
        return Message(
            id=row["id"],
            chat_id=row["chat_id"],
            role=row["role"],
            content=row["content"],
            created_at=_parse(row["created_at"]),
        )