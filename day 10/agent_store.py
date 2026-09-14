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
    context_limit INTEGER,
    recent_messages_limit INTEGER,
    strategy TEXT,
    summary TEXT,
    summary_upto INTEGER NOT NULL DEFAULT 0,
    summary_tokens INTEGER NOT NULL DEFAULT 0,
    facts TEXT,
    facts_tokens INTEGER NOT NULL DEFAULT 0,
    active_branch_id TEXT
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

CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    parent_id TEXT,
    name TEXT NOT NULL,
    upto INTEGER NOT NULL DEFAULT 0
);
"""

_MIGRATIONS = [
    ("messages", "prompt_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("messages", "completion_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("messages", "total_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("agents", "recent_messages_limit", "INTEGER"),
    ("agents", "summary", "TEXT"),
    ("agents", "summary_upto", "INTEGER NOT NULL DEFAULT 0"),
    ("agents", "summary_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("agents", "strategy", "TEXT"),
    ("agents", "facts", "TEXT"),
    ("agents", "facts_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("agents", "active_branch_id", "TEXT"),
    ("messages", "branch_id", "TEXT"),
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
        """Возвращает агентов с их историями и сообщениями веток.

        В "history" попадают только сообщения основного диалога (без метки
        ветки); сообщения веток извлекаются отдельно по branch_id.
        """
        with self._lock:
            agents = self._fetch_agents()
            for agent in agents:
                all_messages = self._fetch_messages(agent["id"])
                agent["history"] = [
                    message
                    for message in all_messages
                    if message.get("branch_id") is None
                ]
                agent["branch_messages"] = {
                    branch_id: [
                        {key: value for key, value in message.items() if key != "branch_id"}
                        for message in all_messages
                        if message.get("branch_id") == branch_id
                    ]
                    for branch_id in {m["branch_id"] for m in all_messages if m.get("branch_id")}
                }
            return agents

    def save_agent(
        self,
        agent_id: str,
        name: str,
        model: str,
        context_limit: Optional[int] = None,
        recent_messages_limit: Optional[int] = None,
        strategy: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO agents (id, name, model, context_limit, recent_messages_limit, strategy) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_id, name, model, context_limit, recent_messages_limit, strategy),
            )
            self._connection.commit()

    def save_summary(
        self,
        agent_id: str,
        summary: str,
        summary_upto: int,
        summary_tokens: int,
    ) -> None:
        """Сохраняет сводку старых сообщений и её границу."""
        with self._lock:
            self._connection.execute(
                "UPDATE agents SET summary = ?, summary_upto = ?, summary_tokens = ? WHERE id = ?",
                (summary, summary_upto, summary_tokens, agent_id),
            )
            self._connection.commit()

    def save_facts(self, agent_id: str, facts: str, facts_tokens: int) -> None:
        """Сохраняет факты диалога (JSON) и расход токенов на их извлечение."""
        with self._lock:
            self._connection.execute(
                "UPDATE agents SET facts = ?, facts_tokens = ? WHERE id = ?",
                (facts, facts_tokens, agent_id),
            )
            self._connection.commit()

    def save_active_branch(self, agent_id: str, branch_id: Optional[str]) -> None:
        """Сохраняет идентификатор активной ветки диалога."""
        with self._lock:
            self._connection.execute(
                "UPDATE agents SET active_branch_id = ? WHERE id = ?",
                (branch_id, agent_id),
            )
            self._connection.commit()

    def save_branch(
        self, branch_id: str, agent_id: str, parent_id: Optional[str], name: str, upto: int
    ) -> None:
        """Создаёт или обновляет ветку диалога."""
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO branches (id, agent_id, parent_id, name, upto) "
                "VALUES (?, ?, ?, ?, ?)",
                (branch_id, agent_id, parent_id, name, upto),
            )
            self._connection.commit()

    def load_branches(self, agent_id: str) -> list[dict]:
        """Возвращает все ветки агента."""
        with self._lock:
            cursor = self._connection.execute(
                "SELECT id, parent_id, name, upto FROM branches WHERE agent_id = ? ORDER BY rowid",
                (agent_id,),
            )
            return [
                {"id": row[0], "parent_id": row[1], "name": row[2], "upto": row[3]}
                for row in cursor.fetchall()
            ]

    def append_message(
        self,
        agent_id: str,
        role: str,
        content: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        branch_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO messages (agent_id, role, content, prompt_tokens, completion_tokens, total_tokens, branch_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (agent_id, role, content, prompt_tokens, completion_tokens, total_tokens, branch_id),
            )
            self._connection.commit()

    def save_branch_messages(self, branch_id: str, agent_id: str, messages: list[dict]) -> None:
        """Заменяет сообщения ветки в базе (используется при её создании)."""
        with self._lock:
            self._connection.execute(
                "DELETE FROM messages WHERE branch_id = ?", (branch_id,)
            )
            for message in messages:
                self._connection.execute(
                    "INSERT INTO messages (agent_id, role, content, prompt_tokens, completion_tokens, total_tokens, branch_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        agent_id,
                        message["role"],
                        message["content"],
                        message.get("prompt_tokens", 0),
                        message.get("completion_tokens", 0),
                        message.get("total_tokens", 0),
                        branch_id,
                    ),
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
            "SELECT id, name, model, context_limit, recent_messages_limit, strategy, summary, "
            "summary_upto, summary_tokens, facts, facts_tokens, active_branch_id "
            "FROM agents ORDER BY rowid"
        )
        return [
            {
                "id": row[0],
                "name": row[1],
                "model": row[2],
                "context_limit": row[3],
                "recent_messages_limit": row[4],
                "strategy": row[5],
                "summary": row[6],
                "summary_upto": row[7],
                "summary_tokens": row[8],
                "facts": row[9],
                "facts_tokens": row[10],
                "active_branch_id": row[11],
            }
            for row in cursor.fetchall()
        ]

    def _fetch_messages(self, agent_id: str) -> list[dict]:
        cursor = self._connection.execute(
            "SELECT role, content, prompt_tokens, completion_tokens, total_tokens, branch_id "
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
                "branch_id": row[5],
            }
            for row in cursor.fetchall()
        ]

    def total_tokens_for_agent(self, agent_id: str) -> int:
        """Сумма total_tokens по сообщениям, суммаризациям и фактам агента."""
        with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(SUM(total_tokens), 0) FROM messages WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            extra_row = self._connection.execute(
                "SELECT COALESCE(summary_tokens, 0) + COALESCE(facts_tokens, 0) "
                "FROM agents WHERE id = ?",
                (agent_id,),
            ).fetchone()
        return int(row[0]) + int(extra_row[0])
