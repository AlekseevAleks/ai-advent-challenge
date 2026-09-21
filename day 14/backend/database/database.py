"""SQLite connection management and schema creation."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from backend.config import get_config
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    model       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          TEXT PRIMARY KEY,
    chat_id     TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_id
    ON messages (chat_id, created_at);

CREATE INDEX IF NOT EXISTS idx_chats_updated_at
    ON chats (updated_at DESC);

-- Working memory: structured state of the task of one chat.
CREATE TABLE IF NOT EXISTS working_memory (
    chat_id     TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
);

-- Long-term memory: durable facts about the user, shared across chats.
CREATE TABLE IF NOT EXISTS long_term_memory (
    id          TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'manual',
    confidence  REAL NOT NULL DEFAULT 1.0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_long_term_category_key
    ON long_term_memory (category, key);

CREATE INDEX IF NOT EXISTS idx_long_term_category
    ON long_term_memory (category);

-- User profiles: HOW the assistant should answer. Deliberately separate from
-- the memory layers, which describe WHAT is known. Each profile is its own
-- row, so profiles never share or overwrite each other's settings.
CREATE TABLE IF NOT EXISTS user_profiles (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    data        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Small key/value store for application state. Currently holds the single
-- active profile id, which is why it is a table and not a column on a profile:
-- "active" is a property of the app, not of any one profile.
CREATE TABLE IF NOT EXISTS app_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Task state: the formalised finite-state-machine position of a task. Kept
-- apart from working memory, which holds free-form task context. One row per
-- task, keyed by task_id (which is the chat id for chat-scoped tasks).
CREATE TABLE IF NOT EXISTS task_states (
    task_id     TEXT PRIMARY KEY,
    chat_id     TEXT NOT NULL,
    stage       TEXT NOT NULL,
    current_step TEXT NOT NULL DEFAULT '',
    expected_action TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,
    data        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_states_chat_id
    ON task_states (chat_id);

-- Invariants: mandatory constraints the assistant must not violate. Kept
-- apart from memory (what is known) and task state (where the task is): an
-- invariant says which solutions are not allowed. Each rule is its own row.
CREATE TABLE IF NOT EXISTS invariants (
    id          TEXT PRIMARY KEY,
    scope       TEXT NOT NULL,
    category    TEXT NOT NULL,
    rule        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,
    priority    TEXT NOT NULL,
    task_id     TEXT NOT NULL DEFAULT '',
    data        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invariants_scope
    ON invariants (scope, status);

CREATE INDEX IF NOT EXISTS idx_invariants_task_id
    ON invariants (task_id);
"""


class Database:
    """Thin wrapper around a SQLite database file.

    A single connection is shared between threads (``check_same_thread=False``)
    and guarded by a lock, which is sufficient for a local single-user app.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else get_config().database_file
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._connection.executescript(SCHEMA)
            self._migrate()
        logger.debug("Database schema ready at %s", self.path)

    def _migrate(self) -> None:
        """Bring an existing database up to the current schema.

        ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so
        columns added in later versions must be applied explicitly. Each step
        is idempotent: it checks the current columns before altering.
        """
        self._ensure_columns(
            "user_profiles",
            {
                "name": "TEXT NOT NULL DEFAULT ''",
                "description": "TEXT NOT NULL DEFAULT ''",
            },
        )
        self._ensure_columns(
            "invariants",
            {"data": "TEXT NOT NULL DEFAULT '{}'"},
        )

    def _ensure_columns(self, table: str, columns: dict) -> None:
        existing = {
            row["name"]
            for row in self._connection.execute(f"PRAGMA table_info({table})")
        }
        if not existing:
            return  # table does not exist yet; SCHEMA already created it
        for column, definition in columns.items():
            if column in existing:
                continue
            self._connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )
            logger.info("Миграция: добавлена колонка %s.%s", table, column)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block inside a transaction, rolling back on error."""
        with self._lock:
            self._connection.execute("BEGIN")
            try:
                yield self._connection
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            else:
                self._connection.execute("COMMIT")

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        """Yield a cursor for read-only queries."""
        with self._lock:
            cursor = self._connection.cursor()
            try:
                yield cursor
            finally:
                cursor.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()


_database: Optional[Database] = None


def get_database() -> Database:
    """Return the process-wide database instance."""
    global _database
    if _database is None:
        _database = Database()
    return _database


def set_database(database: Optional[Database]) -> None:
    """Override the global database instance (used by tests)."""
    global _database
    if _database is not None and _database is not database:
        try:
            _database.close()
        except Exception:  # pragma: no cover - defensive
            pass
    _database = database