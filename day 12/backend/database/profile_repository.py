"""Data access layer for user profiles and application state.

Each profile is its own row in ``user_profiles``, keyed by ``id``. That key is
what keeps profiles isolated: every read and write is scoped to one id, so one
profile can never observe or overwrite another.

The single *active* profile id lives in ``app_state`` rather than as a column on
a profile, because "active" is a property of the application, not of any one
profile. That also makes "only one active profile" true by construction.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from backend.database.database import Database, get_database
from backend.profile.models import UserProfileData

#: The profile used when the caller does not specify one.
DEFAULT_PROFILE_ID = "default"

#: Key under which the active profile id is stored in ``app_state``.
ACTIVE_PROFILE_KEY = "active_profile_id"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class UserProfileRepository:
    """CRUD for user profiles, isolated by profile id."""

    def __init__(self, database: Optional[Database] = None) -> None:
        self._db = database or get_database()

    # ------------------------------------------------------------------ read
    def get(self, profile_id: str = DEFAULT_PROFILE_ID) -> Optional[UserProfileData]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT data FROM user_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            return UserProfileData()
        if not isinstance(payload, dict):
            return UserProfileData()
        return UserProfileData(**payload)

    def get_meta(
        self, profile_id: str = DEFAULT_PROFILE_ID
    ) -> Optional[Tuple[str, str, datetime, datetime]]:
        """Return ``(name, description, created_at, updated_at)`` or ``None``."""
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT name, description, created_at, updated_at"
                " FROM user_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            return None
        return (
            row["name"],
            row["description"],
            _parse(row["created_at"]),
            _parse(row["updated_at"]),
        )

    def get_timestamps(
        self, profile_id: str = DEFAULT_PROFILE_ID
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        meta = self.get_meta(profile_id)
        if meta is None:
            return None, None
        return meta[2], meta[3]

    def exists(self, profile_id: str) -> bool:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT 1 FROM user_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        return row is not None

    def list_ids(self) -> List[str]:
        with self._db.cursor() as cursor:
            rows = cursor.execute(
                "SELECT id FROM user_profiles ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [row["id"] for row in rows]

    def count(self) -> int:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT COUNT(*) AS total FROM user_profiles"
            ).fetchone()
        return int(row["total"]) if row else 0

    # ----------------------------------------------------------------- write
    def save(
        self,
        profile_id: str,
        data: UserProfileData,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Tuple[datetime, datetime]:
        """Insert or update one profile. Returns ``(created_at, updated_at)``."""
        now = utcnow()
        payload = json.dumps(data.model_dump(), ensure_ascii=False)
        resolved_name = name if name is not None else data.name
        resolved_description = (
            description if description is not None else data.description
        )
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO user_profiles"
                " (id, name, description, data, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " name = excluded.name,"
                " description = excluded.description,"
                " data = excluded.data,"
                " updated_at = excluded.updated_at",
                (
                    profile_id,
                    resolved_name,
                    resolved_description,
                    payload,
                    _iso(now),
                    _iso(now),
                ),
            )
        created_at, updated_at = self.get_timestamps(profile_id)
        return created_at or now, updated_at or now

    def delete(self, profile_id: str) -> bool:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM user_profiles WHERE id = ?", (profile_id,)
            )
            return cursor.rowcount > 0

    # ------------------------------------------------------------- app state
    def get_state(self, key: str) -> Optional[str]:
        with self._db.cursor() as cursor:
            row = cursor.execute(
                "SELECT value FROM app_state WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET"
                " value = excluded.value, updated_at = excluded.updated_at",
                (key, value, _iso(utcnow())),
            )

    def get_active_profile_id(self) -> Optional[str]:
        return self.get_state(ACTIVE_PROFILE_KEY)

    def set_active_profile_id(self, profile_id: str) -> None:
        self.set_state(ACTIVE_PROFILE_KEY, profile_id)