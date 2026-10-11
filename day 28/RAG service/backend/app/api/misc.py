"""Эндпоинты поиска, сравнения, истории и настроек."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from ..repositories import jobs_repo
from ..schemas.api import (
    AppSettingsOut,
    ComparisonOut,
    HistoryPage,
    JobSummaryOut,
    SearchRequest,
    SearchResponse,
    SettingsPatch,
)
from ..services.comparison_service import get_comparison
from ..services.job_service import manager
from ..services.search_service import search as do_search
from ..services.settings_service import get_settings_out, patch_settings
from ..utils.errors import NotFoundError

router = APIRouter(prefix="/api", tags=["Поиск, сравнение, история, настройки"])


# ---------------------------------------------------------------------------
# Поиск
# ---------------------------------------------------------------------------

@router.post("/search", summary="Семантический поиск по индексу", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    return do_search(req)


# ---------------------------------------------------------------------------
# Сравнение
# ---------------------------------------------------------------------------

@router.get("/comparison", summary="Сравнение стратегий (все коллекции)", response_model=ComparisonOut)
def comparison_all() -> ComparisonOut:
    return get_comparison(None)


@router.get("/comparison/{collection_id}", summary="Сравнение стратегий в коллекции", response_model=ComparisonOut)
def comparison_collection(collection_id: str) -> ComparisonOut:
    return get_comparison(collection_id)


# ---------------------------------------------------------------------------
# История
# ---------------------------------------------------------------------------

@router.get("/history", summary="История запусков", response_model=HistoryPage)
def history(
    status: Optional[str] = Query(default=None),
    collection_id: Optional[str] = Query(default=None),
    strategy: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> HistoryPage:
    rows = jobs_repo.list_jobs(
        status=status, collection_id=collection_id, strategy=strategy,
        date_from=date_from, date_to=date_to, limit=limit,
    )
    summaries: list[JobSummaryOut] = []
    for r in rows:
        s = manager.summary(r["id"])
        if s:
            summaries.append(s)
    return HistoryPage(jobs=summaries, total=len(summaries))


@router.get("/history/{job_id}", summary="Детали запуска", response_model=JobSummaryOut)
def history_job(job_id: str) -> JobSummaryOut:
    s = manager.summary(job_id)
    if s is None:
        raise NotFoundError("Запуск не найден", code="job_not_found")
    return s


# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

@router.get("/settings", summary="Настройки приложения", response_model=AppSettingsOut)
def get_settings() -> AppSettingsOut:
    return get_settings_out()


@router.patch("/settings", summary="Изменить настройки backend", response_model=AppSettingsOut)
def patch_settings_route(patch: SettingsPatch) -> AppSettingsOut:
    return patch_settings(patch)