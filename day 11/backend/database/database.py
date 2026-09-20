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
        logger.debug("Database schema ready at %s", self.path)

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