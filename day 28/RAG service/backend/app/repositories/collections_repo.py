"""Репозиторий коллекций и индексов."""

from __future__ import annotations

import json
from typing import Any, List, Optional

from ..utils.common import utc_now_iso
from .db import connect, row_to_dict


def create_collection(collection_id: str, name: str, description: str = "") -> dict[str, Any]:
    now = utc_now_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO collections (id, name, description, created_at, updated_at) VALUES (?,?,?,?,?)",
            (collection_id, name, description, now, now),
        )
        row = c.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
    return row_to_dict(row)


def list_collections() -> List[dict[str, Any]]:
    with connect() as c:
        rows = c.execute("SELECT * FROM collections ORDER BY created_at DESC").fetchall()
    return [row_to_dict(r) for r in rows]


def get_collection(collection_id: str) -> Optional[dict[str, Any]]:
    with connect() as c:
        row = c.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
    return row_to_dict(row)


def get_collection_by_name(name: str) -> Optional[dict[str, Any]]:
    with connect() as c:
        row = c.execute("SELECT * FROM collections WHERE name=?", (name,)).fetchone()
    return row_to_dict(row)


def rename_collection(collection_id: str, name: str, description: str) -> Optional[dict[str, Any]]:
    now = utc_now_iso()
    with connect() as c:
        c.execute(
            "UPDATE collections SET name=?, description=?, updated_at=? WHERE id=?",
            (name, description, now, collection_id),
        )
        row = c.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
    return row_to_dict(row)


def delete_collection(collection_id: str) -> bool:
    with connect() as c:
        c.execute("DELETE FROM indexes WHERE collection_id=?", (collection_id,))
        cur = c.execute("DELETE FROM collections WHERE id=?", (collection_id,))
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Индексы
# ---------------------------------------------------------------------------

def get_index(collection_id: str, strategy: str) -> Optional[dict[str, Any]]:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM indexes WHERE collection_id=? AND strategy=?",
            (collection_id, strategy),
        ).fetchone()
    return row_to_dict(row)


def list_indexes(collection_id: str | None = None) -> List[dict[str, Any]]:
    with connect() as c:
        if collection_id:
            rows = c.execute(
                "SELECT * FROM indexes WHERE collection_id=? ORDER BY strategy", (collection_id,)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM indexes ORDER BY collection_id, strategy").fetchall()
    return [row_to_dict(r) for r in rows]


def list_indexes_for_collections(collection_ids: List[str]) -> List[dict[str, Any]]:
    if not collection_ids:
        return []
    marks = ",".join("?" for _ in collection_ids)
    with connect() as c:
        rows = c.execute(
            f"SELECT * FROM indexes WHERE collection_id IN ({marks}) ORDER BY collection_id",
            collection_ids,
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def upsert_index(collection_id: str, strategy: str, index_id: str, config_path: str, config: dict[str, Any]) -> None:
    now = utc_now_iso()
    payload = json.dumps(config, ensure_ascii=False)
    with connect() as c:
        exists = c.execute(
            "SELECT 1 FROM indexes WHERE collection_id=? AND strategy=?", (collection_id, strategy)
        ).fetchone()
        if exists:
            c.execute(
                "UPDATE indexes SET index_id=?, config_path=?, config=?, updated_at=? "
                "WHERE collection_id=? AND strategy=?",
                (index_id, config_path, payload, now, collection_id, strategy),
            )
        else:
            c.execute(
                "INSERT INTO indexes (collection_id, strategy, index_id, config_path, config, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (collection_id, strategy, index_id, config_path, payload, now, now),
            )
        c.execute("UPDATE collections SET updated_at=? WHERE id=?", (now, collection_id))


def delete_index(collection_id: str, strategy: str) -> bool:
    with connect() as c:
        cur = c.execute(
            "DELETE FROM indexes WHERE collection_id=? AND strategy=?", (collection_id, strategy)
        )
    return cur.rowcount > 0


def find_index_by_id(index_id: str) -> Optional[dict[str, Any]]:
    """Найти запись индекса по глобальному index_id."""
    with connect() as c:
        row = c.execute("SELECT * FROM indexes WHERE index_id=?", (index_id,)).fetchone()
    return row_to_dict(row)