"""Репозиторий evaluation датасетов, запусков сравнения и экспериментов."""

from __future__ import annotations

import json
from typing import Any, List, Optional

from ...repositories.db import connect, row_to_dict
from ...utils.common import utc_now_iso


# ---------------------------------------------------------------------------
# Evaluation datasets
# ---------------------------------------------------------------------------

def create_dataset(rec: dict) -> dict:
    now = utc_now_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO eval_datasets (id, name, description, items, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (rec["id"], rec["name"], rec.get("description", ""),
             json.dumps(rec["items"], ensure_ascii=False), now, now),
        )
        row = c.execute("SELECT * FROM eval_datasets WHERE id=?", (rec["id"],)).fetchone()
    return row_to_dict(row)


def list_datasets() -> List[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM eval_datasets ORDER BY created_at DESC").fetchall()
    return [row_to_dict(r) for r in rows]


def get_dataset(dataset_id: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute("SELECT * FROM eval_datasets WHERE id=?", (dataset_id,)).fetchone()
    return row_to_dict(row)


def delete_dataset(dataset_id: str) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM eval_datasets WHERE id=?", (dataset_id,))
    return (cur.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# Evaluation runs
# ---------------------------------------------------------------------------

def create_run(rec: dict) -> dict:
    now = utc_now_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO eval_runs (id, dataset_id, name, status, collection_id, index_id, "
            "config, results, metrics, latency, message, created_at, finished_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rec["id"], rec["dataset_id"], rec.get("name", ""), rec.get("status", "queued"),
             rec.get("collection_id"), rec.get("index_id"),
             json.dumps(rec.get("config", {}), ensure_ascii=False),
             json.dumps(rec.get("results")) if rec.get("results") else None,
             json.dumps(rec.get("metrics")) if rec.get("metrics") else None,
             json.dumps(rec.get("latency")) if rec.get("latency") else None,
             rec.get("message"), now, rec.get("finished_at")),
        )
        row = c.execute("SELECT * FROM eval_runs WHERE id=?", (rec["id"],)).fetchone()
    return row_to_dict(row)


def get_run(run_id: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute("SELECT * FROM eval_runs WHERE id=?", (run_id,)).fetchone()
    return row_to_dict(row)


def list_runs(limit: int = 100) -> List[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [row_to_dict(r) for r in rows]


def update_run(run_id: str, **fields: Any) -> Optional[dict]:
    if not fields:
        return get_run(run_id)
    prepared = {}
    for k, v in fields.items():
        prepared[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
    cols = ", ".join(f"{k}=?" for k in prepared)
    with connect() as c:
        c.execute(f"UPDATE eval_runs SET {cols} WHERE id=?", (*prepared.values(), run_id))
        row = c.execute("SELECT * FROM eval_runs WHERE id=?", (run_id,)).fetchone()
    return row_to_dict(row)


# ---------------------------------------------------------------------------
# Experiments (сохранённые запуски поиска)
# ---------------------------------------------------------------------------

def create_experiment(rec: dict) -> dict:
    now = utc_now_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO experiments (id, name, run_id, dataset_id, collection_id, index_id, "
            "strategy, query, config, metrics, latency, result, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rec["id"], rec["name"], rec.get("run_id"), rec.get("dataset_id"),
             rec.get("collection_id"), rec.get("index_id"), rec.get("strategy"),
             rec["query"], json.dumps(rec["config"], ensure_ascii=False),
             json.dumps(rec.get("metrics")) if rec.get("metrics") else None,
             json.dumps(rec.get("latency")) if rec.get("latency") else None,
             json.dumps(rec["result"], ensure_ascii=False), now),
        )
        row = c.execute("SELECT * FROM experiments WHERE id=?", (rec["id"],)).fetchone()
    return row_to_dict(row)


def get_experiment(experiment_id: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
    return row_to_dict(row)


def list_experiments(limit: int = 200) -> List[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM experiments ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [row_to_dict(r) for r in rows]


def delete_experiment(experiment_id: str) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM experiments WHERE id=?", (experiment_id,))
    return (cur.rowcount or 0) > 0