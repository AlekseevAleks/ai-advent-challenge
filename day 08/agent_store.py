"""Локальное хранилище агентов и их переписки в базе SQLite."""

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from config import DATABASE_FILE

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    context_limit INTEGER
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0
);
"""

_MIGRATIONS = [
    ("messages", "prompt_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("messages", "completion_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("messages", "total_tokens", "INTEGER NOT NULL DEFAULT 0"),
]


class AgentStore:
    """Сохраняет агентов и сообщения; восстанавливает их после перезапуска."""

    def __init__(self, database_file: Path = DATABASE_FILE):
        # Gradio вызывает обработчики из разных потоков, поэтому соединение
        # должно быть общим, а доступ к нему - последовательным.
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(database_file, check_same_thread=False)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(_CREATE_TABLES)
        self._apply_migrations()
        self._rename_max_tokens_column()
        self._connection.commit()

    def _apply_migrations(self) -> None:
        """Добавляет недостающие колонки в базу, созданную раньше."""
        for table, column, definition in _MIGRATIONS:
            columns = {
                row[1] for row in self._connection.execute(f"PRAGMA table_info({table})")
            }
            if column not in columns:
                self._connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )

    def _rename_max_tokens_column(self) -> None:
        """Переименовывает колонку max_tokens в context_limit (старые базы)."""
        columns = [
            row[1] for row in self._connection.execute("PRAGMA table_info(agents)")
        ]
        if "max_tokens" in columns:
            self._connection.execute(
                "ALTER TABLE agents RENAME COLUMN max_tokens TO context_limit"
            )

    def load_agents(self) -> list[dict]:
        """Возвращает всех агентов с их полной историей сообщений."""
        with self._lock:
            agents = self._fetch_agents()
            for agent in agents:
                agent["history"] = self._fetch_messages(agent["id"])
            return agents

    def save_agent(
        self,
        agent_id: str,
        name: str,
        model: str,
        context_limit: Optional[int] = None,
    ) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO agents (id, name, model, context_limit) VALUES (?, ?, ?, ?)",
                (agent_id, name, model, context_limit),
            )
            self._connection.commit()

    def append_message(
        self,
        agent_id: str,
        role: str,
        content: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO messages (agent_id, role, content, prompt_tokens, completion_tokens, total_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_id, role, content, prompt_tokens, completion_tokens, total_tokens),
            )
            self._connection.commit()

    def delete_agent(self, agent_id: str) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
            self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def _fetch_agents(self) -> list[dict]:
        cursor = self._connection.execute(
            "SELECT id, name, model, context_limit FROM agents ORDER BY rowid"
        )
        return [
            {"id": row[0], "name": row[1], "model": row[2], "context_limit": row[3]}
            for row in cursor.fetchall()
        ]

    def _fetch_messages(self, agent_id: str) -> list[dict]:
        cursor = self._connection.execute(
            "SELECT role, content, prompt_tokens, completion_tokens, total_tokens "
            "FROM messages WHERE agent_id = ? ORDER BY id",
            (agent_id,),
        )
        return [
            {
                "role": row[0],
                "content": row[1],
                "prompt_tokens": row[2],
                "completion_tokens": row[3],
                "total_tokens": row[4],
            }
            for row in cursor.fetchall()
        ]

    def total_tokens_for_agent(self, agent_id: str) -> int:
        """Сумма total_tokens по всем сообщениям агента."""
        with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(SUM(total_tokens), 0) FROM messages WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        return int(row[0])
