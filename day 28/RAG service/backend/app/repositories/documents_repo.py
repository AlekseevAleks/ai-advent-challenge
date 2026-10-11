"""Репозиторий документов."""

from __future__ import annotations

import json
from typing import Any, List, Optional

from ..utils.common import utc_now_iso
from .db import connect, row_to_dict


def create_document(rec: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    with connect() as c:
        c.execute(
            """INSERT INTO documents
               (id, original_name, storage_name, file_type, file_size, path,
                extracted_path, char_count, page_count, status, warnings, errors,
                content_hash, created_at, extracted_at, indexed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec["id"], rec["original_name"], rec["storage_name"], rec["file_type"],
                rec["file_size"], rec["path"], rec.get("extracted_path"),
                rec.get("char_count"), rec.get("page_count"), rec.get("status", "uploaded"),
                json.dumps(rec.get("warnings", [])), json.dumps(rec.get("errors", [])),
                rec["content_hash"], rec.get("created_at", now), rec.get("extracted_at"), None,
            ),
        )
        row = c.execute("SELECT * FROM documents WHERE id=?", (rec["id"],)).fetchone()
    return row_to_dict(row)


def get_document(doc_id: str) -> Optional[dict[str, Any]]:
    with connect() as c:
        row = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return row_to_dict(row)


def list_documents(include: List[str] | None = None) -> List[dict[str, Any]]:
    with connect() as c:
        if include:
            marks = ",".join("?" for _ in include)
            rows = c.execute(
                f"SELECT * FROM documents WHERE id IN ({marks}) ORDER BY created_at DESC",
                include,
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
    return [row_to_dict(r) for r in rows]


def update_document(doc_id: str, **fields: Any) -> Optional[dict[str, Any]]:
    if not fields:
        return get_document(doc_id)
    prepared: dict[str, Any] = {}
    for k, v in fields.items():
        if isinstance(v, (list, dict)):
            prepared[k] = json.dumps(v, ensure_ascii=False)
        else:
            prepared[k] = v
    cols = ", ".join(f"{k}=?" for k in prepared)
    values = list(prepared.values())
    with connect() as c:
        c.execute(f"UPDATE documents SET {cols} WHERE id=?", (*values, doc_id))
        row = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return row_to_dict(row)


def delete_document(doc_id: str) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    return cur.rowcount > 0


def document_stats() -> dict[str, Any]:
    with connect() as c:
        total = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        ready = c.execute("SELECT COUNT(*) FROM documents WHERE status='ready'").fetchone()[0]
        indexed = c.execute("SELECT COUNT(*) FROM documents WHERE status='indexed'").fetchone()[0]
        errors = c.execute("SELECT COUNT(*) FROM documents WHERE status='error'").fetchone()[0]
        pages = c.execute("SELECT COALESCE(SUM(page_count),0) FROM documents").fetchone()[0]
        chars = c.execute("SELECT COALESCE(SUM(char_count),0) FROM documents").fetchone()[0]
        bytes_sum = c.execute("SELECT COALESCE(SUM(file_size),0) FROM documents").fetchone()[0]
    return {
        "total": total, "ready": ready, "indexed": indexed,
        "errors": errors, "pages": pages, "char_count": chars, "file_bytes": bytes_sum,
    }