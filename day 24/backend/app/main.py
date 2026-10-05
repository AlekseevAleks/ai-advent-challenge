"""Точка входа FastAPI-приложения."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .api import collections, documents, health, indexing, misc, ollama, rag
from .config import get_base_settings
from .repositories import db
from .repositories import jobs_repo
from .services import runtime
from .utils.errors import AppError, error_payload
from .utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- старт ---
    setup_logging(get_base_settings().log_level)
    paths = runtime.ensure_dirs()
    db_path = db.init_db(paths.root)
    runtime.load_overrides()
    interrupted = jobs_repo.mark_interrupted_jobs(
        "Задание прервано перезапуском приложения (поток остановлен)."
    )
    if interrupted:
        logger.warning("Помечено %d заданий как прерванные после перезапуска", interrupted)
    logger.info("Хранилище: %s (БД: %s)", paths.root, db_path)
    yield
    # --- остановка ---


app = FastAPI(
    title="RAG Document Indexing Lab API",
    description=(
        "Локальный учебный сервис индексации документов для RAG: загрузка файлов, "
        "извлечение текста, две стратегии chunking, эмбеддинги через локальный Ollama, "
        "векторные индексы FAISS, поиск и сравнение стратегий."
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_base_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Обработчики ошибок: единый формат {"detail": ..., "code": ...}
# ---------------------------------------------------------------------------

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_payload(exc))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", []) if x not in ("body", "query", "path"))
        errors.append(f"{loc}: {err.get('msg')}" if loc else err.get("msg"))
    return JSONResponse(
        status_code=422,
        content={"detail": "Некорректные параметры запроса", "code": "validation_error",
                 "details": errors[:20]},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Необработанная ошибка на %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Внутренняя ошибка сервера: {exc}", "code": "internal_error"},
    )


# ---------------------------------------------------------------------------
# Роутеры
# ---------------------------------------------------------------------------

app.include_router(health.router)
app.include_router(ollama.router)
app.include_router(documents.router)
app.include_router(indexing.router)
app.include_router(collections.router)
app.include_router(misc.router)
app.include_router(rag.router)


@app.get("/api/stats/overview", tags=["Система"], summary="Сводная статистика для «Обзора»")
def overview() -> dict:
    from .services.stats_service import get_overview
    return get_overview().model_dump()


@app.get("/api/summary", tags=["Система"], include_in_schema=False)
def api_summary() -> dict:
    return {"paths": sorted({route.path for route in app.routes if hasattr(route, "path")})}