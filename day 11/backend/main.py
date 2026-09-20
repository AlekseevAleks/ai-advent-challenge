"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api import chats, memory, models, settings
from backend.config import get_config
from backend.database.database import get_database
from backend.utils.errors import AppError
from backend.utils.logging_config import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = get_config()
    config.ensure_data_dir()
    get_database()  # create schema on startup
    logger.info("AI Chat запущен. Данные: %s", config.data_dir)
    yield
    logger.info("AI Chat остановлен.")


def create_app() -> FastAPI:
    config = get_config()
    setup_logging(config.log_level)

    app = FastAPI(
        title="Local AI Chat",
        description="Локальный чат с LLM через OpenAI-compatible API.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # The frontend is served from the same origin; CORS is only useful when the
    # UI is opened from a different dev server.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost", "http://127.0.0.1"],
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(settings.router)
    app.include_router(models.router)
    app.include_router(chats.router)
    app.include_router(memory.router)

    _register_error_handlers(app)
    _mount_frontend(app, config)

    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("Ошибка приложения [%s]: %s", exc.code, exc.message)
        else:
            logger.info("Ошибка приложения [%s]: %s", exc.code, exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        message = first.get("msg", "Некорректные данные запроса.")
        if field:
            message = f"{field}: {message}"
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": message}},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Необработанная ошибка сервера")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Внутренняя ошибка сервера. Подробности в логах.",
                }
            },
        )


def _mount_frontend(app: FastAPI, config) -> None:
    frontend_dir = config.frontend_dir
    static_dir = frontend_dir / "static"
    index_file = frontend_dir / "index.html"

    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(str(index_file))

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> JSONResponse:
        return JSONResponse(status_code=204, content=None)

    @app.get("/health", tags=["system"])
    async def health() -> dict:
        return {"status": "ok"}


app = create_app()