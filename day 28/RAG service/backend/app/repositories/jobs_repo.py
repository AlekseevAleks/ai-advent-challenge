"""Репозиторий заданий (история запусков)."""

from __future__ import annotations

import json
from typing import Any, List, Optional

from ..utils.common import utc_now_iso
from .db import connect, row_to_dict


def create_job(rec: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    with connect() as c:
        c.execute(
            """INSERT INTO jobs
               (id, status, mode, collection_id, collection_name, strategies,
                document_ids, request, model, progress, result, message,
                created_at, started_at, finished_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec["id"], rec.get("status", "queued"), rec.get("mode"),
                rec.get("collection_id"), rec.get("collection_name"),
                json.dumps(rec.get("strategies", [])), json.dumps(rec.get("document_ids", [])),
                json.dumps(rec.get("request", {}), ensure_ascii=False), rec.get("model"),
                json.dumps(rec.get("progress", {})), json.dumps(rec.get("result")),
                rec.get("message"), rec.get("created_at", now),
                rec.get("started_at"), rec.get("finished_at"),
            ),
        )
        row = c.execute("SELECT * FROM jobs WHERE id=?", (rec["id"],)).fetchone()
    return row_to_dict(row)


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with connect() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return row_to_dict(row)


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values())
    with connect() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*values, job_id))


def list_jobs(
    status: Optional[str] = None,
    collection_id: Optional[str] = None,
    strategy: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[dict[str, Any]]:
    where: List[str] = []
    args: List[Any] = []
    if status:
        where.append("status=?")
        args.append(status)
    if collection_id:
        where.append("collection_id=?")
        args.append(collection_id)
    if date_from:
        where.append("created_at>=?")
        args.append(date_from)
    if date_to:
        where.append("created_at<=?")
        args.append(date_to)
    sql = "SELECT * FROM jobs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    with connect() as c:
        rows = c.execute(sql, args).fetchall()
    out = [row_to_dict(r) for r in rows]
    if strategy and not collection_id:
        out = [j for j in out if strategy in json.loads(j["strategies"])]
    return out


def count_jobs() -> dict[str, int]:
    with connect() as c:
        total = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        ok = c.execute("SELECT COUNT(*) FROM jobs WHERE status='completed'").fetchone()[0]
        with_err = c.execute("SELECT COUNT(*) FROM jobs WHERE status='completed_with_errors'").fetchone()[0]
        failed = c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('failed','cancelled')").fetchone()[0]
        running = c.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
    return {"total": total, "ok": ok, "with_errors": with_err, "failed": failed, "running": running}


def last_indexed_at() -> Optional[str]:
    with connect() as c:
        row = c.execute(
            "SELECT MAX(finished_at) AS t FROM jobs WHERE status IN ('completed','completed_with_errors')"
        ).fetchone()
    return row["t"] if row else None


def mark_interrupted_jobs(message: str) -> int:
    """После перезапуска приложения пометить задания, зависшие в состоянии выполнения."""
    with connect() as c:
        cur = c.execute(
            "UPDATE jobs SET status='failed', message=?, finished_at=? "
            "WHERE status IN ('queued','running')",
            (message, utc_now_iso()),
        )
    return cur.rowcount or 0