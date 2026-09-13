"""Локальное хранилище агентов и их переписки в базе SQLite."""

import sqlite3
import threading
from pathlib import Path

from config import DATABASE_FILE

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    model TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL
);
"""


class AgentStore:
    """Сохраняет агентов и сообщения; восстанавливает их после перезапуска."""

    def __init__(self, database_file: Path = DATABASE_FILE):
        # Gradio вызывает обработчики из разных потоков, поэтому соединение
        # должно быть общим, а доступ к нему - последовательным.
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(database_file, check_same_thread=False)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(_CREATE_TABLES)
        self._connection.commit()

    def load_agents(self) -> list[dict]:
        """Возвращает всех агентов с их полной историей сообщений."""
        with self._lock:
            agents = self._fetch_agents()
            for agent in agents:
                agent["history"] = self._fetch_messages(agent["id"])
            return agents

    def save_agent(self, agent_id: str, name: str, model: str) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO agents (id, name, model) VALUES (?, ?, ?)",
                (agent_id, name, model),
            )
            self._connection.commit()

    def append_message(self, agent_id: str, role: str, content: str) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO messages (agent_id, role, content) VALUES (?, ?, ?)",
                (agent_id, role, content),
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
            "SELECT id, name, model FROM agents ORDER BY rowid"
        )
        return [
            {"id": row[0], "name": row[1], "model": row[2]}
            for row in cursor.fetchall()
        ]

    def _fetch_messages(self, agent_id: str) -> list[dict]:
        cursor = self._connection.execute(
            "SELECT role, content FROM messages WHERE agent_id = ? ORDER BY id",
            (agent_id,),
        )
        return [{"role": row[0], "content": row[1]} for row in cursor.fetchall()]
