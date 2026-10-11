"""Менеджер фоновых заданий индексации.

Задания выполняются в фоновых потоках. Прогресс хранится в памяти и
периодически сохраняется в SQLite — после перезапуска приложения можно
продолжить просмотр истории (зависшие задания помечаются как failed).
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional

from ..repositories import jobs_repo
from ..schemas.api import JobProgressOut, JobSummaryOut, STAGE_LABELS
from ..utils.common import now_epoch, utc_now_iso
from ..utils.ids import new_id
from ..utils.logging import get_logger

logger = get_logger(__name__)


class JobCancelled(Exception):
    """Задание отменено пользователем (между batch-запросами)."""


class JobManager:
    """Управление жизненным циклом заданий."""

    def __init__(self) -> None:
        self._cancel: Dict[str, threading.Event] = {}
        self._progress: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    def create(self, request: Any) -> str:
        """Создать задание в статусе queued, вернуть job_id."""
        job_id = new_id("job")
        payload = request.model_dump()
        jobs_repo.create_job({
            "id": job_id,
            "status": "queued",
            "mode": payload.get("mode"),
            "collection_id": payload.get("collection_id"),
            "collection_name": payload.get("collection_name"),
            "strategies": payload.get("strategies", []),
            "document_ids": payload.get("document_ids", []),
            "request": payload,
            "model": payload.get("embedding_model"),
            "started_at": None,
            "finished_at": None,
        })
        with self._lock:
            self._progress[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "stage": "prepare",
                "percent": 0.0,
                "document_index": 0,
                "document_total": len(payload.get("document_ids", [])),
                "current_document": None,
                "chunks": 0,
                "embeddings_done": 0,
                "errors": 0,
                "message": "В очереди",
                "elapsed_seconds": 0.0,
                "started_epoch": None,
                "updated_at": utc_now_iso(),
                "request": payload,
            }
        return job_id

    def start(self, job_id: str, target) -> None:
        """Запустить задание в фоновом потоке."""
        event = threading.Event()
        with self._lock:
            self._cancel[job_id] = event
            p = self._progress.get(job_id)
            if p:
                p["status"] = "running"
                p["started_epoch"] = now_epoch()
                p["message"] = "Запуск…"
        self.persist(job_id)
        thread = threading.Thread(
            target=self._run_wrapped, args=(job_id, target), daemon=True,
            name=f"job-{job_id}",
        )
        thread.start()

    def _run_wrapped(self, job_id: str, target) -> None:
        try:
            target(job_id)
        except JobCancelled:
            self.finish(job_id, "cancelled", message="Задание отменено пользователем")
        except Exception as e:  # noqa: BLE001
            logger.exception("Задание %s упало", job_id)
            self.finish(job_id, "failed", message=f"Ошибка задания: {e}")
        finally:
            with self._lock:
                self._cancel.pop(job_id, None)

    # ------------------------------------------------------------------
    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            p = self._progress.get(job_id)
            if p is None:
                return
            p.update(fields)
            p["updated_at"] = utc_now_iso()
            if p.get("started_epoch"):
                p["elapsed_seconds"] = now_epoch() - p["started_epoch"]
            p["cancel_requested"] = job_id in self._cancel and self._cancel[job_id].is_set()
        self.persist(job_id)

    def set_stage(self, job_id: str, stage: str, percent: float, message: str) -> None:
        self.update(
            job_id,
            stage=stage,
            percent=percent,
            message=message,
            stage_label=STAGE_LABELS.get(stage, stage),
        )

    def check_cancel(self, job_id: str) -> None:
        ev = self._cancel.get(job_id)
        if ev is not None and ev.is_set():
            raise JobCancelled()

    def request_cancel(self, job_id: str) -> bool:
        ev = self._cancel.get(job_id)
        if ev is None:
            # задание не выполняется (возможно, уже завершено)
            return False
        ev.set()
        self.update(job_id, cancel_requested=True, message="Отмена запрошена…")
        return True

    def finish(self, job_id: str, status: str, result: Optional[dict] = None,
               message: Optional[str] = None) -> None:
        self.update(
            job_id,
            status=status,
            stage="done",
            percent=100.0,
            message=message,
            result=result,
            finished_at=utc_now_iso(),
        )

    def add_error(self, job_id: str, text: str) -> None:
        with self._lock:
            p = self._progress.get(job_id)
            if p is None:
                return
            errs = p.get("error_messages", [])
            errs.append(text)
            p["error_messages"] = errs
            p["errors"] = len(errs)
        self.persist(job_id)

    def persist(self, job_id: str) -> None:
        with self._lock:
            p = self._progress.get(job_id)
            if p is None:
                return
            snapshot = {k: v for k, v in p.items() if k not in ("request",)}
        fields = {
            "status": snapshot.get("status", "queued"),
            "message": snapshot.get("message"),
            "progress": json.dumps(snapshot, ensure_ascii=False),
        }
        if snapshot.get("started_epoch"):
            fields["started_at"] = jobs_repo.get_job(job_id).get("started_at") \
                or utc_now_iso()
        if snapshot.get("finished_at"):
            fields["finished_at"] = snapshot["finished_at"]
        if snapshot.get("result") is not None:
            fields["result"] = json.dumps(snapshot["result"], ensure_ascii=False)
        jobs_repo.update_job(job_id, **fields)

    # ------------------------------------------------------------------
    def get_progress(self, job_id: str) -> Optional[JobProgressOut]:
        with self._lock:
            p = self._progress.get(job_id)
            if p is not None:
                snap = dict(p)
        if snap is None:
            row = jobs_repo.get_job(job_id)
            if row is None:
                return None
            snap = json.loads(row.get("progress") or "{}")
            snap["job_id"] = row["id"]
            snap["status"] = row["status"]
            snap["message"] = row.get("message") or snap.get("message")
            snap["result"] = json.loads(row["result"]) if row.get("result") else None
        req = snap.get("request") or {}
        elapsed = snap.get("elapsed_seconds", 0.0)
        if snap.get("started_epoch"):
            elapsed = now_epoch() - snap["started_epoch"]
        return JobProgressOut(
            job_id=snap.get("job_id", job_id),
            status=snap.get("status", "queued"),
            stage=snap.get("stage", "prepare"),
            stage_label=snap.get("stage_label") or STAGE_LABELS.get(snap.get("stage", "prepare")),
            percent=float(snap.get("percent", 0.0)),
            document_index=int(snap.get("document_index", 0)),
            document_total=int(snap.get("document_total", 0)),
            current_document=snap.get("current_document"),
            chunks=int(snap.get("chunks", 0)),
            embeddings_done=int(snap.get("embeddings_done", 0)),
            errors=int(snap.get("errors", 0)),
            message=snap.get("message"),
            elapsed_seconds=round(float(elapsed), 1),
            updated_at=snap.get("updated_at") or utc_now_iso(),
            cancel_requested=bool(snap.get("cancel_requested", False)),
            result=snap.get("result"),
            collection_id=req.get("collection_id"),
            collection_name=req.get("collection_name"),
        )

    def summary(self, job_id: str) -> Optional[JobSummaryOut]:
        row = jobs_repo.get_job(job_id)
        if row is None:
            return None
        progress = json.loads(row.get("progress") or "{}")
        strategies = json.loads(row.get("strategies") or "[]")
        doc_ids = json.loads(row.get("document_ids") or "[]")
        result = json.loads(row["result"]) if row.get("result") else None
        started = row.get("started_at")
        finished = row.get("finished_at")
        duration = None
        if started and finished:
            from ..utils.common import parse_iso
            try:
                duration = (parse_iso(finished) - parse_iso(started)).total_seconds()
            except Exception:  # noqa: BLE001
                duration = None
        return JobSummaryOut(
            job_id=row["id"],
            status=row["status"],
            mode=row.get("mode") or "",
            collection_id=row.get("collection_id"),
            collection_name=row.get("collection_name"),
            strategies=strategies,
            model=row.get("model"),
            documents=len(doc_ids),
            chunks=int(progress.get("chunks", 0)),
            embeddings_ok=int(progress.get("embeddings_done", 0)),
            errors=int(progress.get("errors", 0)),
            progress_percent=float(progress.get("percent", 0.0)),
            message=row.get("message") or progress.get("message"),
            created_at=row.get("created_at") or "",
            started_at=started,
            finished_at=finished,
            duration_seconds=round(duration, 1) if duration else None,
            result=result,
        )

    def list_summaries(self, **filters: Any) -> list[JobSummaryOut]:
        rows = jobs_repo.list_jobs(limit=filters.pop("limit", 200), **filters)
        return [self.summary(r["id"]) for r in rows if self.summary(r["id"]) is not None]


manager = JobManager()