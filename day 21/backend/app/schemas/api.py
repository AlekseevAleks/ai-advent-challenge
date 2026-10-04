"""Схемы заданий, поиска, сравнения, истории и настроек."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Задания
# ---------------------------------------------------------------------------

JobStatus = Literal["queued", "running", "completed", "completed_with_errors", "failed", "cancelled"]

STAGES = [
    "prepare",       # 1. Подготовка документов
    "extract",       # 2. Извлечение текста
    "chunking",      # 3. Chunking
    "embeddings",    # 4. Генерация эмбеддингов
    "faiss",         # 5. Построение FAISS
    "metadata",      # 6. Сохранение метаданных
    "integrity",     # 7. Проверка целостности
    "done",          # 8. Завершение
]

STAGE_LABELS = {
    "prepare": "Подготовка документов",
    "extract": "Извлечение текста",
    "chunking": "Chunking",
    "embeddings": "Генерация эмбеддингов",
    "faiss": "Построение FAISS",
    "metadata": "Сохранение метаданных",
    "integrity": "Проверка целостности",
    "done": "Завершение",
}


class JobProgressOut(BaseModel):
    job_id: str
    status: JobStatus
    stage: str
    stage_label: str
    percent: float = 0.0
    document_index: int = 0
    document_total: int = 0
    current_document: Optional[str] = None
    chunks: int = 0
    embeddings_done: int = 0
    errors: int = 0
    message: Optional[str] = None
    elapsed_seconds: float = 0.0
    updated_at: str
    cancel_requested: bool = False
    result: Optional[Dict[str, Any]] = None
    collection_id: Optional[str] = None
    collection_name: Optional[str] = None


class JobListOut(BaseModel):
    jobs: List["JobSummaryOut"]
    total: int


class JobSummaryOut(BaseModel):
    job_id: str
    status: JobStatus
    mode: str
    collection_id: Optional[str] = None
    collection_name: Optional[str] = None
    strategies: List[str] = Field(default_factory=list)
    model: Optional[str] = None
    documents: int = 0
    chunks: int = 0
    embeddings_ok: int = 0
    errors: int = 0
    progress_percent: float = 0.0
    message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    result: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Поиск
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    collection_id: str
    strategy: Literal["fixed_size", "structural"]
    query: str = Field(min_length=1, max_length=20_000)
    top_k: int = Field(default=5, ge=1, le=50)


class SearchResultItem(BaseModel):
    rank: int
    score: float
    chunk: Dict[str, Any]


class SearchResponse(BaseModel):
    query: str
    collection_id: str
    strategy: str
    model: str
    dimension: int
    n_indexed: int
    took_ms: float
    results: List[SearchResultItem] = Field(default_factory=list)
    note: str = (
        "Cosine similarity — это оценка векторного сходства текстов, "
        "а не гарантированная вероятность правильности ответа."
    )


# ---------------------------------------------------------------------------
# Сравнение стратегий
# ---------------------------------------------------------------------------

class ComparisonMetrics(BaseModel):
    documents: int = 0
    chunks: int = 0
    mean_chars: float = 0.0
    median_chars: float = 0.0
    min_chars: int = 0
    max_chars: int = 0
    std_chars: float = 0.0
    empty_chunks: int = 0
    index_size_bytes: int = 0
    time_chunking_ms: Optional[float] = None
    time_embeddings_ms: Optional[float] = None
    time_total_ms: Optional[float] = None
    errors: int = 0


class ComparisonOut(BaseModel):
    collection_id: str
    collection_name: str
    strategies: List[str] = Field(default_factory=list)
    metrics: Dict[str, ComparisonMetrics] = Field(default_factory=dict)
    sizes: Dict[str, List[int]] = Field(default_factory=dict)                 # для box plot
    histogram: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)  # buckets per strategy
    per_document: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    timings: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    tradeoffs: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# История
# ---------------------------------------------------------------------------

class HistoryFilters(BaseModel):
    status: Optional[str] = None
    collection_id: Optional[str] = None
    strategy: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class HistoryPage(BaseModel):
    jobs: List[JobSummaryOut]
    total: int


# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

class BackendSettingsOut(BaseModel):
    ollama_url: str
    embedding_model: str
    embedding_batch_size: int
    embedding_retries: int
    ollama_timeout: float
    ollama_connection_timeout: float
    max_file_size_mb: int
    max_files_per_request: int
    storage_dir: str
    default_chunk_size: int
    default_chunk_overlap: int
    default_structural_max_chunk_size: int
    default_structural_min_chunk_size: int
    allowed_extensions: List[str]


class SettingsPatch(BaseModel):
    ollama_url: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_batch_size: Optional[int] = Field(default=None, ge=1, le=512)
    embedding_retries: Optional[int] = Field(default=None, ge=0, le=10)
    ollama_timeout: Optional[float] = Field(default=None, gt=0)
    ollama_connection_timeout: Optional[float] = Field(default=None, gt=0)
    max_file_size_mb: Optional[int] = Field(default=None, ge=1, le=1024)
    max_files_per_request: Optional[int] = Field(default=None, ge=1, le=1000)
    default_chunk_size: Optional[int] = Field(default=None, ge=50, le=100_000)
    default_chunk_overlap: Optional[int] = Field(default=None, ge=0)
    default_structural_max_chunk_size: Optional[int] = Field(default=None, ge=100, le=200_000)
    default_structural_min_chunk_size: Optional[int] = Field(default=None, ge=50)


class AppSettingsOut(BaseModel):
    app_name: str
    version: str
    backend: BackendSettingsOut
    ollama: Dict[str, Any]
    storage: Dict[str, Any]


class OverviewStatsOut(BaseModel):
    backend_status: str
    apps: Dict[str, Any] = Field(default_factory=dict)
    documents: Dict[str, Any] = Field(default_factory=dict)
    chunks: Dict[str, Any] = Field(default_factory=dict)
    collections: Dict[str, Any] = Field(default_factory=dict)
    jobs: Dict[str, Any] = Field(default_factory=dict)
    charts: Dict[str, Any] = Field(default_factory=dict)