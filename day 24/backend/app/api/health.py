"""Состояние системы."""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..schemas.common import MessageResponse
from ..services import runtime

router = APIRouter(prefix="/api", tags=["Система"])


@router.get("/health", summary="Статус backend")
def health() -> dict:
    s = runtime.effective_settings()
    paths = runtime.get_paths()
    return {
        "status": "ok",
        "app_name": s.app_name,
        "version": __version__,
        "storage_dir": str(paths.root),
        "python": "3.11+",
    }


@router.get("/", include_in_schema=False)
def root() -> MessageResponse:
    return MessageResponse(message="RAG Document Indexing Lab API. Swagger: /docs")