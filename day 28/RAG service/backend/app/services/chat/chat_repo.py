"""Репозиторий чата: беседы, сообщения и Task Memory (таблицы conversations/messages/task_states)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ...repositories.db import connect, row_to_dict
from ...utils.common import utc_now_iso
from ...utils.ids import new_id
from ...services.chat.task_memory import TaskState


def get_or_create_conversation(conversation_id: Optional[str] = None) -> dict:
    now = utc_now_iso()
    with connect() as c:
        if conversation_id:
            row = c.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if row is not None:
                c.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
                return row_to_dict(row)
        cid = conversation_id or new_id("conv")
        c.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (cid, "", now, now),
        )
        row = c.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
    return row_to_dict(row)


def list_conversations(limit: int = 100) -> List[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [row_to_dict(r) for r in rows]


def add_message(conversation_id: str, role: str, content: str,
                status: str = "", search_query: Optional[str] = None,
                sources: Optional[List[dict]] = None, citations: Optional[List[dict]] = None,
                retrieval: Optional[dict] = None) -> dict:
    now = utc_now_iso()
    msg_id = new_id("msg")
    with connect() as c:
        c.execute(
            "INSERT INTO messages (id, conversation_id, role, content, status, search_query, "
            "sources, citations, retrieval, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (msg_id, conversation_id, role, content, status, search_query,
             json.dumps(sources or [], ensure_ascii=False),
             json.dumps(citations or [], ensure_ascii=False),
             json.dumps(retrieval) if retrieval else None, now),
        )
        c.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
        row = c.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
    return row_to_dict(row)


def _message_out(row: dict) -> dict:
    return {
        "id": row["id"], "conversation_id": row["conversation_id"], "role": row["role"],
        "content": row["content"], "status": row["status"],
        "search_query": row["search_query"],
        "sources": json.loads(row["sources"] or "[]"),
        "citations": json.loads(row["citations"] or "[]"),
        "retrieval": json.loads(row["retrieval"]) if row["retrieval"] else None,
        "created_at": row["created_at"],
    }


def get_messages(conversation_id: str) -> List[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
    return [_message_out(r) for r in rows]


def recent_messages(conversation_id: str, limit: int = 10) -> List[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM (SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?) "
            "ORDER BY created_at ASC",
            (conversation_id, limit),
        ).fetchall()
    return [_message_out(r) for r in rows]


# ---------------------------------------------------------------------------
# Task Memory
# ---------------------------------------------------------------------------

def get_task_state(conversation_id: str) -> TaskState:
    with connect() as c:
        row = c.execute("SELECT * FROM task_states WHERE conversation_id=?", (conversation_id,)).fetchone()
    if row is None:
        return TaskState()
    return TaskState.from_dict(json.loads(row["state"] or "{}"))


def save_task_state(conversation_id: str, state: TaskState) -> dict:
    now = utc_now_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO task_states (conversation_id, state, version, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(conversation_id) DO UPDATE SET state=excluded.state, "
            "version=excluded.version, updated_at=excluded.updated_at",
            (conversation_id, json.dumps(state.to_dict(), ensure_ascii=False), state.version, now),
        )
        row = c.execute("SELECT * FROM task_states WHERE conversation_id=?", (conversation_id,)).fetchone()
    return row_to_dict(row)


def conversation_out(conversation_id: str) -> dict:
    conv = get_or_create_conversation(conversation_id)
    return {
        "conversation_id": conv["id"],
        "messages": get_messages(conv["id"]),
        "task_state": get_task_state(conv["id"]).to_dict(),
        "created_at": conv["created_at"],
        "updated_at": conv["updated_at"],
    }
