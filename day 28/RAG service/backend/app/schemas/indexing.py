"""Схемы индексации, коллекций и индексов."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Параметры chunking
# ---------------------------------------------------------------------------

class FixedSizeParams(BaseModel):
    chunk_size: int = Field(default=1200, ge=50, le=200_000)
    overlap: int = Field(default=200, ge=0, le=100_000)
    unit: Literal["chars", "tokens"] = "chars"

    @model_validator(mode="after")
    def _check(self) -> "FixedSizeParams":
        if self.overlap >= self.chunk_size:
            raise ValueError("Overlap должен быть меньше размера чанка")
        return self


class StructuralParams(BaseModel):
    max_chunk_size: int = Field(default=1500, ge=100, le=500_000)
    min_chunk_size: int = Field(default=200, ge=50)
    merge_small_sections: bool = True

    @model_validator(mode="after")
    def _check(self) -> "StructuralParams":
        if self.min_chunk_size > self.max_chunk_size:
            raise ValueError("min_chunk_size не может быть больше max_chunk_size")
        return self


STRATEGIES = ("fixed_size", "structural")


class JobRequest(BaseModel):
    """Запрос на запуск задания индексации."""

    document_ids: List[str] = Field(min_length=1)
    strategies: List[Literal["fixed_size", "structural"]] = Field(min_length=1)
    mode: Literal["new_collection", "new_index", "rebuild", "add"]
    collection_id: Optional[str] = None
    collection_name: Optional[str] = None
    fixed_size: Optional[FixedSizeParams] = None
    structural: Optional[StructuralParams] = None
    embedding_model: Optional[str] = None
    embedding_batch_size: Optional[int] = Field(default=None, ge=1, le=512)

    @model_validator(mode="after")
    def _check_mode(self) -> "JobRequest":
        if self.mode == "new_collection" and not (self.collection_name or "").strip():
            raise ValueError("Для новой коллекции укажите её название")
        if self.mode == "new_collection" and self.collection_id:
            raise ValueError("Для новой коллекции collection_id не указывается")
        if self.mode in ("new_index", "rebuild", "add") and not self.collection_id:
            raise ValueError("Укажите существующую коллекцию (collection_id)")
        if self.collection_id and self.collection_name:
            raise ValueError("Нельзя одновременно указывать collection_id и collection_name")
        return self


# ---------------------------------------------------------------------------
# Коллекции и индексы
# ---------------------------------------------------------------------------

class IndexConfigOut(BaseModel):
    """Метаданные индекса (config.json)."""

    index_id: str
    collection_id: str
    strategy: str
    embedding_model: str
    dimension: int
    schema_version: int
    index_version: int
    num_vectors: int
    num_documents: int
    document_ids: List[str] = Field(default_factory=list)
    chunking_params: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    size_bytes: int = 0
    time_chunking_ms: Optional[float] = None
    time_embeddings_ms: Optional[float] = None
    time_total_ms: Optional[float] = None
    job_id: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    errors_count: int = 0


class IndexStatsOut(IndexConfigOut):
    chunks: int = 0
    mean_chars: float = 0.0
    median_chars: float = 0.0
    min_chars: int = 0
    max_chars: int = 0
    std_chars: float = 0.0
    empty_chunks: int = 0


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class CollectionOut(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: str
    updated_at: str
    strategies: List[str] = Field(default_factory=list)
    indexes: List[IndexConfigOut] = Field(default_factory=list)


class JobResultIndex(BaseModel):
    collection_id: str
    strategy: str
    index_id: str
    num_vectors: int
    num_documents: int
    action: str
    size_bytes: int = 0
    dimension: int = 0


class JobResult(BaseModel):
    collection_id: str
    collection_name: str
    indexes: List[JobResultIndex] = Field(default_factory=list)
    documents: int = 0
    chunks: int = 0
    embeddings_ok: int = 0
    embeddings_failed: int = 0
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    time_chunking_ms: Optional[float] = None
    time_embeddings_ms: Optional[float] = None
    time_total_ms: Optional[float] = None