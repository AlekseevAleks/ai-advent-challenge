"""Сводная статистика для страницы «Обзор» и сравнение чанков по стратегиям."""

from __future__ import annotations

import json
import statistics
from typing import Any, Dict, List

from .. import __version__
from ..repositories import collections_repo, documents_repo, jobs_repo
from ..schemas.api import OverviewStatsOut
from ..utils.common import median
from . import runtime
from .faiss_store import get_store


def _all_chunk_metadata() -> List[dict]:
    store = get_store()
    out: List[dict] = []
    for rec in collections_repo.list_indexes():
        f = store.metadata_file(rec["collection_id"], rec["strategy"])
        if f.exists():
            try:
                out.extend(json.loads(f.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                continue
    return out


def _histogram_sizes(sizes: List[int]) -> List[Dict[str, Any]]:
    if not sizes:
        return []
    lo, hi = min(sizes), max(sizes)
    if hi <= lo:
        return [{"label": str(lo), "count": len(sizes)}]
    n = 10
    step = max(1, int((hi - lo) / n) or 1)
    lo = int(lo)
    buckets: Dict[int, int] = {}
    for s in sizes:
        b = int((s - lo) // step) * step + lo
        buckets[b] = buckets.get(b, 0) + 1
    return [{"label": f"{b}–{b + step}", "count": c} for b, c in sorted(buckets.items())]


def get_overview() -> OverviewStatsOut:
    s = runtime.effective_settings()
    doc_stats = documents_repo.document_stats()
    indexes = collections_repo.list_indexes()
    collections = collections_repo.list_collections()
    jobs = jobs_repo.count_jobs()

    chunks_by_strategy: Dict[str, int] = {}
    for rec in indexes:
        config = rec["config"] if isinstance(rec["config"], dict) else json.loads(rec["config"])
        chunks_by_strategy[rec["strategy"]] = chunks_by_strategy.get(rec["strategy"], 0) + config.get("num_vectors", 0)

    metas = _all_chunk_metadata()
    sizes = [m["char_count"] for m in metas if isinstance(m.get("char_count"), int)]
    store = get_store()
    index_sizes = [
        {
            "collection_id": rec["collection_id"],
            "strategy": rec["strategy"],
            "size_bytes": store.index_size_bytes(rec["collection_id"], rec["strategy"]),
        }
        for rec in indexes
    ]

    recent_jobs = jobs_repo.list_jobs(limit=10)
    running = [
        {
            "job_id": r["id"], "status": r["status"],
            "strategies": json.loads(r["strategies"] or "[]"),
            "message": r.get("message"),
        }
        for r in recent_jobs if r["status"] in ("queued", "running")
    ]

    return OverviewStatsOut(
        backend_status="ok",
        apps={
            "version": __version__,
            "name": s.app_name,
            "storage_dir": str(runtime.get_paths().root),
        },
        documents={
            **doc_stats,
            "limit_mb": s.max_file_size_mb,
            "max_files": s.max_files_per_request,
        },
        chunks={
            "total": sum(chunks_by_strategy.values()),
            "by_strategy": [{"strategy": k, "chunks": v} for k, v in sorted(chunks_by_strategy.items())],
            "median_size": median([float(x) for x in sizes]) if sizes else 0,
            "mean_size": round(statistics.fmean(sizes), 1) if sizes else 0,
            "min_size": min(sizes) if sizes else 0,
            "max_size": max(sizes) if sizes else 0,
            "sample_sizes": sizes[:200],
        },
        collections={
            "total": len(collections),
            "indexes": len(indexes),
            "list": [{"id": c["id"], "name": c["name"]} for c in collections],
            "index_sizes": index_sizes,
        },
        jobs={
            **jobs,
            "last_indexed_at": jobs_repo.last_indexed_at(),
            "recent": [
                {
                    "job_id": r["id"], "status": r["status"],
                    "created_at": r.get("created_at"),
                    "finished_at": r.get("finished_at"),
                    "strategies": json.loads(r["strategies"] or "[]"),
                }
                for r in recent_jobs
            ],
            "running": running,
        },
        charts={
            "chunks_by_strategy": chunks_by_strategy,
            "size_histogram": _histogram_sizes(sizes),
            "last_durations": [
                {
                    "job_id": r["id"],
                    "label": r["id"],
                    "ms": (json.loads(r["result"]) or {}).get("time_total_ms")
                    if r.get("result") else None,
                    "status": r["status"],
                }
                for r in recent_jobs
                if r["status"] in ("completed", "completed_with_errors", "failed")
            ],
            "index_sizes": index_sizes,
        },
    )