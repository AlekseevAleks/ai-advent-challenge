"""Репозиторий рантайм-настроек (переопределения поверх .env)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .db import connect


def get_all() -> Dict[str, str]:
    with connect() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def get(key: str) -> Optional[str]:
    with connect() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set(key: str, value: Any) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def set_many(values: Dict[str, Any]) -> None:
    with connect() as c:
        for k, v in values.items():
            c.execute(
                "INSERT INTO settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v)),
            )