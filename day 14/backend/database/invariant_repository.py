"""Data access layer for invariants.

Each invariant is its own row, keyed by ``id``. The structured columns
(``scope``, ``category``, ``status``, ``priority``, ``task_id``) are duplicated
out of the JSON blob so they can be filtered and indexed directly, while
``data`` keeps the full record.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from backend.database.database import Database, get_database
from backend.invariants.models import InvariantData

#: The scope id used for project-wide invariants.
GLOBAL_SCOPE_ID = "global"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class InvariantRepository:
    """CRUD for invariants."""

    def __init__(self, database: Optional[Database] = None) -> None:
        self._db = database or get_database()

    # ------------------------------------------------------------------ read
    def get(self, invariant_id: str) -> Optional[InvariantData]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT data FROM invariants WHERE id = ?", (invariant_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            return InvariantData()
        if not isinstance(payload, dict):
            return InvariantData()
        return InvariantData(**payload)

    def get_timestamps(
        self, invariant_id: str
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT created_at, updated_at FROM invariants WHERE id = ?",
                (invariant_id,),
            ).fetchone()
        if row is None:
            return None, None
        return _parse(row["created_at"]), _parse(row["updated_at"])

    def exists(self, invariant_id: str) -> bool:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT 1 FROM invariants WHERE id = ?", (invariant_id,)
            ).fetchone()
        return row is not None

    def list_all(self) -> List[str]:
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                "SELECT id FROM invariants ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [row["id"] for row in rows]

    def list_ids(
        self,
        *,
        scope: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[str]:
        """Ids matching the given filters, newest last."""
        clauses: List[str] = []
        params: List[object] = []
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                f"SELECT id FROM invariants{where} ORDER BY created_at ASC, id ASC",
                params,
            ).fetchall()
        return [row["id"] for row in rows]

    def count(self) -> int:
        with self._db.cursor() as cursor:
            row = cursor.execute("SELECT COUNT(*) AS total FROM invariants").fetchone()
        return int(row["total"]) if row else 0

    # ----------------------------------------------------------------- write
    def save(self, invariant_id: str, data: InvariantData) -> Tuple[datetime, datetime]:
        """Insert or update one invariant. Returns ``(created, updated)``."""
        now = utcnow()
        payload = json.dumps(data.model_dump(), ensure_ascii=False)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO invariants"
                " (id, scope, category, rule, description, status, priority,"
                "  task_id, data, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " scope = excluded.scope,"
                " category = excluded.category,"
                " rule = excluded.rule,"
                " description = excluded.description,"
                " status = excluded.status,"
                " priority = excluded.priority,"
                " task_id = excluded.task_id,"
                " data = excluded.data,"
                " updated_at = excluded.updated_at",
                (
                    invariant_id,
                    data.scope,
                    data.category,
                    data.rule,
                    data.description,
                    data.status,
                    data.priority,
                    data.task_id,
                    payload,
                    _iso(now),
                    _iso(now),
                ),
            )
        created_at, updated_at = self.get_timestamps(invariant_id)
        return created_at or now, updated_at or now

    def delete(self, invariant_id: str) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM invariants WHERE id = ?", (invariant_id,)
            )
            return cursor.rowcount > 0

    def delete_for_task(self, task_id: str) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM invariants WHERE task_id = ?", (task_id,)
            )
            return cursor.rowcount
