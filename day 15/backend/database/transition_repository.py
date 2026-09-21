"""Data access layer for the configurable task lifecycle.

Three tables, three responsibilities:

* ``task_state_definitions`` — the vocabulary of states (data, not code);
* ``transition_rules``       — which moves are allowed and under which conditions;
* ``task_state_transitions`` — the audit trail of every attempt.

Rules are read from the database on every transition, which is what makes a
rule edited in the UI apply to the very next request without a restart.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from backend.database.database import Database, get_database
from backend.transitions.models import (
    Condition,
    TaskStateDefinition,
    TransitionHistoryEntry,
    TransitionRule,
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


def _load_conditions(raw: str) -> List[Condition]:
    """Parse the stored condition list, dropping anything unusable."""
    try:
        payload = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(payload, list):
        return []
    conditions: List[Condition] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            conditions.append(Condition(**item))
        except Exception:  # noqa: BLE001 - a broken condition is dropped
            continue
    return conditions


class TaskStateDefinitionRepository:
    """CRUD for the states of the lifecycle."""

    def __init__(self, database: Optional[Database] = None) -> None:
        self._db = database or get_database()

    # ------------------------------------------------------------------ read
    def get(self, state_id: str) -> Optional[TaskStateDefinition]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT * FROM task_state_definitions WHERE id = ?", (state_id,)
            ).fetchone()
        return self._row_to_state(row) if row else None

    def exists(self, state_id: str) -> bool:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT 1 FROM task_state_definitions WHERE id = ?", (state_id,)
            ).fetchone()
        return row is not None

    def list_all(self) -> List[TaskStateDefinition]:
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM task_state_definitions ORDER BY position ASC, created_at ASC"
            ).fetchall()
        return [self._row_to_state(row) for row in rows]

    def count(self) -> int:
        with self._db.cursor() as cursor:
            row = cursor.execute("SELECT COUNT(*) AS total FROM task_state_definitions").fetchone()
        return int(row["total"]) if row else 0

    def next_position(self) -> int:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT COALESCE(MAX(position), -1) AS last FROM task_state_definitions"
            ).fetchone()
        return int(row["last"]) + 1 if row else 0

    # ----------------------------------------------------------------- write
    def save(self, state: TaskStateDefinition) -> None:
        now = utcnow()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO task_state_definitions"
                " (id, name, description, is_initial, is_final, active, position,"
                "  created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " name = excluded.name,"
                " description = excluded.description,"
                " is_initial = excluded.is_initial,"
                " is_final = excluded.is_final,"
                " active = excluded.active,"
                " position = excluded.position,"
                " updated_at = excluded.updated_at",
                (
                    state.id,
                    state.name,
                    state.description,
                    int(state.is_initial),
                    int(state.is_final),
                    int(state.active),
                    state.position,
                    _iso(now),
                    _iso(now),
                ),
            )

    def clear_initial(self, *, except_id: Optional[str] = None) -> None:
        """Drop the initial flag from every state (at most one is initial)."""
        with self._db.transaction() as conn:
            if except_id is None:
                conn.execute("UPDATE task_state_definitions SET is_initial = 0")
            else:
                conn.execute(
                    "UPDATE task_state_definitions SET is_initial = 0 WHERE id != ?",
                    (except_id,),
                )

    def delete(self, state_id: str) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute("DELETE FROM task_state_definitions WHERE id = ?", (state_id,))
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_state(row) -> TaskStateDefinition:
        return TaskStateDefinition(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            is_initial=bool(row["is_initial"]),
            is_final=bool(row["is_final"]),
            active=bool(row["active"]),
            position=int(row["position"]),
            created_at=_parse(row["created_at"]),
            updated_at=_parse(row["updated_at"]),
            exists=True,
        )


class TransitionRuleRepository:
    """CRUD for transition rules."""

    def __init__(self, database: Optional[Database] = None) -> None:
        self._db = database or get_database()

    # ------------------------------------------------------------------ read
    def get(self, rule_id: str) -> Optional[TransitionRule]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT * FROM transition_rules WHERE id = ?", (rule_id,)
            ).fetchone()
        return self._row_to_rule(row) if row else None

    def exists(self, rule_id: str) -> bool:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT 1 FROM transition_rules WHERE id = ?", (rule_id,)
            ).fetchone()
        return row is not None

    def list_all(self) -> List[TransitionRule]:
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM transition_rules ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [self._row_to_rule(row) for row in rows]

    def list_active(self) -> List[TransitionRule]:
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM transition_rules WHERE active = 1"
                " ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [self._row_to_rule(row) for row in rows]

    def find(self, from_state: str, to_state: str) -> List[TransitionRule]:
        """Rules for one edge, active or not."""
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM transition_rules"
                " WHERE from_state = ? AND to_state = ?"
                " ORDER BY created_at ASC",
                (from_state, to_state),
            ).fetchall()
        return [self._row_to_rule(row) for row in rows]

    def list_for_state(self, state_id: str) -> List[TransitionRule]:
        """Rules that mention a state on either end."""
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM transition_rules"
                " WHERE from_state = ? OR to_state = ?"
                " ORDER BY created_at ASC",
                (state_id, state_id),
            ).fetchall()
        return [self._row_to_rule(row) for row in rows]

    def count(self) -> int:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT COUNT(*) AS total FROM transition_rules"
            ).fetchone()
        return int(row["total"]) if row else 0

    # ----------------------------------------------------------------- write
    def save(self, rule: TransitionRule) -> None:
        now = utcnow()
        payload = json.dumps(
            [condition.model_dump() for condition in rule.conditions],
            ensure_ascii=False,
        )
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO transition_rules"
                " (id, from_state, to_state, name, description, condition,"
                "  conditions, active, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " from_state = excluded.from_state,"
                " to_state = excluded.to_state,"
                " name = excluded.name,"
                " description = excluded.description,"
                " condition = excluded.condition,"
                " conditions = excluded.conditions,"
                " active = excluded.active,"
                " updated_at = excluded.updated_at",
                (
                    rule.id,
                    rule.from_state,
                    rule.to_state,
                    rule.name,
                    rule.description,
                    rule.condition,
                    payload,
                    int(rule.active),
                    _iso(now),
                    _iso(now),
                ),
            )

    def delete(self, rule_id: str) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM transition_rules WHERE id = ?", (rule_id,)
            )
            return cursor.rowcount > 0

    @staticmethod
    def _row_to_rule(row) -> TransitionRule:
        return TransitionRule(
            id=row["id"],
            from_state=row["from_state"],
            to_state=row["to_state"],
            name=row["name"],
            description=row["description"],
            condition=row["condition"],
            conditions=_load_conditions(row["conditions"]),
            active=bool(row["active"]),
            created_at=_parse(row["created_at"]),
            updated_at=_parse(row["updated_at"]),
            exists=True,
        )


class TransitionHistoryRepository:
    """Append-only log of transition attempts."""

    def __init__(self, database: Optional[Database] = None) -> None:
        self._db = database or get_database()

    def record(
        self,
        *,
        task_id: str,
        from_stage: str,
        to_stage: str,
        trigger: str = "manual",
        reason: str = "",
        result: str = "success",
    ) -> TransitionHistoryEntry:
        entry_id = str(uuid.uuid4())
        now = utcnow()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO task_state_transitions"
                " (id, task_id, from_stage, to_stage, trigger, reason, result,"
                "  created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry_id,
                    task_id,
                    from_stage,
                    to_stage,
                    trigger,
                    reason,
                    result,
                    _iso(now),
                ),
            )
        return TransitionHistoryEntry(
            id=entry_id,
            task_id=task_id,
            from_stage=from_stage,
            to_stage=to_stage,
            trigger=trigger,
            reason=reason,
            result=result,
            created_at=now,
        )

    def list_for_task(
        self, task_id: str, *, limit: int = 50
    ) -> List[TransitionHistoryEntry]:
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                "SELECT * FROM task_state_transitions WHERE task_id = ?"
                " ORDER BY created_at DESC, id DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        return [
            TransitionHistoryEntry(
                id=row["id"],
                task_id=row["task_id"],
                from_stage=row["from_stage"],
                to_stage=row["to_stage"],
                trigger=row["trigger"],
                reason=row["reason"],
                result=row["result"],
                created_at=_parse(row["created_at"]),
            )
            for row in rows
        ]

    def count(self) -> int:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT COUNT(*) AS total FROM task_state_transitions"
            ).fetchone()
        return int(row["total"]) if row else 0

    def delete_for_task(self, task_id: str) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM task_state_transitions WHERE task_id = ?", (task_id,)
            )
            return cursor.rowcount
