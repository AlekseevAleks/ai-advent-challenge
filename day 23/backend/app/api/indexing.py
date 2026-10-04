"""Эндпоинты индексации (задания)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Response, status

from ..schemas.api import JobListOut, JobProgressOut, JobSummaryOut
from ..schemas.indexing import JobRequest
from ..services.indexing_service import indexing_service
from ..services.job_service import manager
from ..utils.errors import AppError, NotFoundError

router = APIRouter(prefix="/api/indexing", tags=["Индексация"])


@router.post("/jobs", summary="Запустить задание индексации", status_code=status.HTTP_201_CREATED)
def create_job(req: JobRequest) -> dict:
    job_id = indexing_service.submit(req)
    return {"job_id": job_id, "status": "queued", "detail": "Задание поставлено в очередь"}


@router.get("/jobs", summary="Список заданий", response_model=JobListOut)
def list_jobs(limit: int = 100, offset: int = 0) -> JobListOut:
    rows = manager.list_summaries(limit=min(limit, 500), offset=offset)
    summaries = [s for s in rows if s is not None]
    return JobListOut(jobs=summaries, total=len(summaries))


@router.get("/jobs/{job_id}", summary="Статус задания", response_model=JobProgressOut)
def get_job(job_id: str) -> JobProgressOut:
    progress = manager.get_progress(job_id)
    if progress is None:
        raise NotFoundError("Задание не найдено", code="job_not_found")
    return progress


@router.get("/jobs/{job_id}/result", summary="Результат задания")
def get_job_result(job_id: str) -> dict:
    progress = manager.get_progress(job_id)
    if progress is None:
        raise NotFoundError("Задание не найдено", code="job_not_found")
    if progress.status not in ("completed", "completed_with_errors", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail="Задание ещё не завершено")
    return progress.result or {"message": "Результат недоступен"}


@router.post("/jobs/{job_id}/cancel", summary="Отмена задания")
def cancel_job(job_id: str) -> dict:
    if manager.get_progress(job_id) is None:
        raise NotFoundError("Задание не найдено", code="job_not_found")
    requested = manager.request_cancel(job_id)
    return {"job_id": job_id, "cancel_requested": requested,
            "message": "Отмена запрошена. Задание остановится между пакетами."}