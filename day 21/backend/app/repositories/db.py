"""Слой доступа к SQLite.

Проект использует стандартный модуль sqlite3: состояние приложения (документы,
коллекции, индексы, история заданий, рантайм-настройки) хранится в одном файле
`storage/app.db`. Полные тексты документов и чанков хранятся в JSON-файлах рядом
с индексами — так БД остаётся лёгкой.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

_write_lock = threading.RLock()
_db_path: Optional[Path] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id             TEXT PRIMARY KEY,
    original_name  TEXT NOT NULL,
    storage_name   TEXT NOT NULL,
    file_type      TEXT NOT NULL,
    file_size      INTEGER NOT NULL,
    path           TEXT NOT NULL,
    extracted_path TEXT,
    char_count     INTEGER,
    page_count     INTEGER,
    status         TEXT NOT NULL,
    warnings       TEXT NOT NULL DEFAULT '[]',
    errors         TEXT NOT NULL DEFAULT '[]',
    content_hash   TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    extracted_at   TEXT,
    indexed_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);

CREATE TABLE IF NOT EXISTS collections (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Один активный индекс на (коллекция, стратегия); перестроение атомарно заменяет файлы.
CREATE TABLE IF NOT EXISTS indexes (
    collection_id TEXT NOT NULL,
    strategy      TEXT NOT NULL,
    index_id      TEXT NOT NULL,
    config_path   TEXT NOT NULL,
    config        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (collection_id, strategy)
);

CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    mode            TEXT,
    collection_id   TEXT,
    collection_name TEXT,
    strategies      TEXT NOT NULL,
    document_ids    TEXT NOT NULL,
    request         TEXT NOT NULL,
    model           TEXT,
    progress        TEXT NOT NULL DEFAULT '{}',
    result          TEXT,
    message         TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def init_db(storage_dir: Path) -> Path:
    """Создать каталог и схему БД, вернуть путь к файлу app.db."""
    global _db_path
    storage_dir.mkdir(parents=True, exist_ok=True)
    path = storage_dir / "app.db"
    _db_path = path
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return path


def _conn() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("init_db() не вызывался: БД не инициализирована")
    conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = _conn()
    try:
        yield conn
        conn.commit()  # commit лучший вариант для коротких операций чтения
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def connect_for_app() -> sqlite3.Connection:
    """Соединение для фоновых потоков (не закрывается автоматически)."""
    conn = _conn()
    return conn


def close_connections() -> None:
    """Закрыть резервные соединения (используется в тестах)."""
    global _db_path
    _db_path = None