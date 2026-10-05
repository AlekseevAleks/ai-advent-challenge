"""Репозиторий grounded-ответов (таблица rag_answers)."""

from __future__ import annotations

import json
from typing import Any, List, Optional

from ...repositories.db import connect, row_to_dict
from ...utils.common import utc_now_iso


def create_answer(rec: dict) -> dict:
    now = utc_now_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO rag_answers (id, query, rewritten_query, collection_id, index_id, strategy, "
            "status, answer, answer_model, relevance_score, grounding_score, grounding_threshold, "
            "relevance_threshold, claims_total, claims_supported, prompt_version, config, sources, "
            "citations, claims, retrieval, latency, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rec["id"], rec["query"], rec.get("rewritten_query"),
                rec.get("collection_id"), rec.get("index_id"), rec.get("strategy"),
                rec["status"], rec["answer"], rec.get("answer_model"),
                rec.get("relevance_score"), rec.get("grounding_score"),
                rec.get("grounding_threshold"), rec.get("relevance_threshold"),
                rec.get("claims_total", 0), rec.get("claims_supported", 0),
                rec.get("prompt_version"),
                json.dumps(rec.get("config", {}), ensure_ascii=False),
                json.dumps(rec.get("sources", []), ensure_ascii=False),
                json.dumps(rec.get("citations", []), ensure_ascii=False),
                json.dumps(rec.get("claims", []), ensure_ascii=False),
                json.dumps(rec.get("retrieval"), ensure_ascii=False) if rec.get("retrieval") else None,
                json.dumps(rec.get("latency")) if rec.get("latency") else None,
                now,
            ),
        )
        row = c.execute("SELECT * FROM rag_answers WHERE id=?", (rec["id"],)).fetchone()
    return row_to_dict(row)


def get_answer(answer_id: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute("SELECT * FROM rag_answers WHERE id=?", (answer_id,)).fetchone()
    return row_to_dict(row)


def list_answers(limit: int = 100) -> List[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM rag_answers ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def delete_answer(answer_id: str) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM rag_answers WHERE id=?", (answer_id,))
    return (cur.rowcount or 0) > 0


def answer_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "query": row["query"],
        "rewritten_query": row.get("rewritten_query"),
        "collection_id": row.get("collection_id"),
        "index_id": row.get("index_id"),
        "strategy": row.get("strategy"),
        "status": row["status"],
        "answer": row["answer"],
        "answer_model": row.get("answer_model"),
        "relevance_score": row.get("relevance_score"),
        "grounding_score": row.get("grounding_score"),
        "grounding_threshold": row.get("grounding_threshold"),
        "relevance_threshold": row.get("relevance_threshold"),
        "claims_total": row.get("claims_total", 0),
        "claims_supported": row.get("claims_supported", 0),
        "prompt_version": row.get("prompt_version"),
        "config": json.loads(row["config"] or "{}"),
        "sources": json.loads(row["sources"] or "[]"),
        "citations": json.loads(row["citations"] or "[]"),
        "claims": json.loads(row["claims"] or "[]"),
        "retrieval": json.loads(row["retrieval"]) if row.get("retrieval") else None,
        "latency": json.loads(row["latency"]) if row.get("latency") else None,
        "created_at": row.get("created_at"),
    }


# ---------------------------------------------------------------------------
# Grounded evaluation runs
# ---------------------------------------------------------------------------

def create_eval_answer_run(rec: dict) -> dict:
    now = utc_now_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO eval_answer_runs (id, name, status, dataset_id, collection_id, index_id, "
            "strategy, config, per_question, metrics, message, created_at, finished_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rec["id"], rec.get("name", ""), rec.get("status", "running"),
                rec.get("dataset_id"), rec.get("collection_id"), rec.get("index_id"),
                rec.get("strategy"), json.dumps(rec.get("config", {}), ensure_ascii=False),
                json.dumps(rec.get("per_question"), ensure_ascii=False) if rec.get("per_question") else None,
                json.dumps(rec.get("metrics")) if rec.get("metrics") else None,
                rec.get("message"), now, rec.get("finished_at"),
            ),
        )
        row = c.execute("SELECT * FROM eval_answer_runs WHERE id=?", (rec["id"],)).fetchone()
    return row_to_dict(row)


def update_eval_answer_run(run_id: str, **fields: Any) -> Optional[dict]:
    if not fields:
        return get_eval_answer_run(run_id)
    prepared = {}
    for k, v in fields.items():
        prepared[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
    cols = ", ".join(f"{k}=?" for k in prepared)
    with connect() as c:
        c.execute(f"UPDATE eval_answer_runs SET {cols} WHERE id=?", (*prepared.values(), run_id))
        row = c.execute("SELECT * FROM eval_answer_runs WHERE id=?", (run_id,)).fetchone()
    return row_to_dict(row)


def get_eval_answer_run(run_id: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute("SELECT * FROM eval_answer_runs WHERE id=?", (run_id,)).fetchone()
    return row_to_dict(row)


def list_eval_answer_runs(limit: int = 100) -> List[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM eval_answer_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def eval_answer_run_out(row: dict) -> dict:
    return {
        "id": row["id"], "name": row.get("name", ""), "status": row["status"],
        "dataset_id": row.get("dataset_id"), "collection_id": row.get("collection_id"),
        "index_id": row.get("index_id"), "strategy": row.get("strategy"),
        "config": json.loads(row["config"] or "{}"),
        "per_question": json.loads(row["per_question"]) if row.get("per_question") else None,
        "metrics": json.loads(row["metrics"]) if row.get("metrics") else None,
        "message": row.get("message"), "created_at": row.get("created_at"),
        "finished_at": row.get("finished_at"),
    }
