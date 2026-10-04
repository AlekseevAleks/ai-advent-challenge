"""Общие схемы: ошибки, сообщения, чанки, страницы."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None
    details: Optional[Any] = None


class MessageResponse(BaseModel):
    message: str


class PageInfo(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0
    total_pages: int = 0


class PaginationMeta(BaseModel):
    pagination: PageInfo


class ChunkOut(BaseModel):
    """Метаданные чанка (схема метаданных v1)."""

    model_config = ConfigDict(extra="allow")

    chunk_id: str
    document_id: str
    source: str
    title: str
    section: Optional[str] = None
    text: str
    chunk_index: int
    chunking_strategy: str
    start_offset: int
    end_offset: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    char_count: int
    embedding_model: str
    collection_id: str
    index_version: int = 1
    symbol_type: Optional[str] = None
    symbol_name: Optional[str] = None
    # Дополнительная диагностика, вычисляется на лету из индекса
    similarity: Optional[float] = Field(default=None, description="Оценка сходства (только для поиска)")
    rank: Optional[int] = None