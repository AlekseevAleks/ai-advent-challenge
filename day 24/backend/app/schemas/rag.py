"""Схемы модуля «Reranking & Filtering» (учебный RAG-pipeline)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

QUERY_MAX_LENGTH = 2000


# ---------------------------------------------------------------------------
# Конфигурация pipeline
# ---------------------------------------------------------------------------

class RetrievalConfig(BaseModel):
    """Конфигурация одного запуска pipeline (совпадает с конфигом эксперимента)."""

    query_rewrite: bool = False
    query_rewrite_model: Optional[str] = None

    initial_top_k: int = Field(default=20, ge=1, le=500)
    final_top_k: int = Field(default=5, ge=1, le=100)

    enable_filter: bool = True
    similarity_threshold: float = Field(default=0.65, ge=0.0, le=1.0)

    enable_reranker: bool = True
    reranker: Literal["heuristic", "cross_encoder", "similarity"] = "heuristic"
    reranker_model: Optional[str] = None
    reranker_query: Literal["original", "rewritten"] = "original"

    deduplicate: bool = False
    dedup_threshold: float = Field(default=0.97, ge=0.0, le=1.0)
    mmr: bool = False
    mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check(self) -> "RetrievalConfig":
        if self.initial_top_k < self.final_top_k:
            raise ValueError("initial_top_k должен быть не меньше final_top_k")
        return self


# ---------------------------------------------------------------------------
# Запросы/ответы API
# ---------------------------------------------------------------------------

class QueryRewriteRequest(BaseModel):
    query: str = Field(min_length=1, max_length=QUERY_MAX_LENGTH)
    model: Optional[str] = None


class QueryRewriteResponse(BaseModel):
    original_query: str
    rewritten_query: str
    model: str
    latency_ms: float = 0.0


class RetrieveRequest(BaseModel):
    collection_id: Optional[str] = None
    index_id: Optional[str] = None
    strategy: Optional[Literal["fixed_size", "structural"]] = None
    query: str = Field(min_length=1, max_length=QUERY_MAX_LENGTH)
    top_k: int = Field(default=20, ge=1, le=500)


class FilterRequest(BaseModel):
    scores: List[float] = Field(min_length=1)
    threshold: float = Field(ge=0.0, le=1.0)


class FilterResponse(BaseModel):
    threshold: float
    passed: int
    filtered: int
    kept_positions: List[int]


class RerankRequest(BaseModel):
    query: str = Field(min_length=1, max_length=QUERY_MAX_LENGTH)
    documents: List[str] = Field(min_length=1, max_length=500)
    reranker: Literal["heuristic", "cross_encoder", "similarity"] = "heuristic"
    model: Optional[str] = None
    base_scores: Optional[List[float]] = None


class RerankResponse(BaseModel):
    reranker: str
    model: Optional[str]
    scores: List[float]
    reranked_positions: List[int]


class RagSearchRequest(BaseModel):
    collection_id: Optional[str] = None
    index_id: Optional[str] = None
    strategy: Optional[Literal["fixed_size", "structural"]] = None
    query: str = Field(min_length=1, max_length=QUERY_MAX_LENGTH)
    config: RetrievalConfig = Field(default_factory=RetrievalConfig)


class RerankerStatus(BaseModel):
    reranker: str
    model: Optional[str] = None
    available: bool
    reason: Optional[str] = None
    install_hint: Optional[str] = None


class RerankersStatus(BaseModel):
    heuristic: RerankerStatus
    cross_encoder: RerankerStatus
    similarity: RerankerStatus
    default_reranker: str
    default_model: str


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

class EvalItem(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    expected_sources: List[str] = Field(default_factory=list)
    expected_sections: List[str] = Field(default_factory=list)
    relevant_chunk_ids: List[str] = Field(default_factory=list)


class EvalDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    items: List[EvalItem] = Field(min_length=1)


class EvalDatasetOut(BaseModel):
    id: str
    name: str
    description: str = ""
    items: List[EvalItem] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class EvalRunRequest(BaseModel):
    """Запуск полного сравнения режимов по датасету (конфиг применяется к каждому).

    Моды сравнения задаются через `modes` (см. MODE_WAYS в evaluation_service).
    Дополнительные настройки (threshold, initial/final top-k, reranker) — базовые.
    """

    collection_id: Optional[str] = None
    index_id: Optional[str] = None
    strategy: Optional[Literal["fixed_size", "structural"]] = None
    modes: List[str] = Field(default_factory=list, max_length=6)
    base_config: RetrievalConfig = Field(default_factory=RetrievalConfig)
    name: str = ""
    dataset_id: Optional[str] = None


class EvalRunOut(BaseModel):
    id: str
    dataset_id: str
    name: str = ""
    status: str = "queued"     # queued|running|completed|failed
    collection_id: Optional[str] = None
    index_id: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    results: Optional[Dict[str, Any]] = None       # per-mode aggregate
    metrics: Optional[Dict[str, Any]] = None
    latency: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    created_at: str = ""
    finished_at: Optional[str] = None


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    collection_id: Optional[str] = None
    index_id: Optional[str] = None
    strategy: Optional[str] = None
    query: str = Field(min_length=1, max_length=QUERY_MAX_LENGTH)
    config: RetrievalConfig = Field(default_factory=RetrievalConfig)
    result: Dict[str, Any]
    run_id: Optional[str] = None
    dataset_id: Optional[str] = None


class ExperimentOut(BaseModel):
    id: str
    name: str
    collection_id: Optional[str] = None
    index_id: Optional[str] = None
    strategy: Optional[str] = None
    query: str
    config: Dict[str, Any]
    metrics: Optional[Dict[str, Any]] = None
    latency: Optional[Dict[str, Any]] = None
    result: Dict[str, Any]
    created_at: str = ""


class ExperimentCompareOut(BaseModel):
    current: ExperimentOut
    compared: ExperimentOut
    metrics_delta: Dict[str, Any]

# ---------------------------------------------------------------------------
# Grounded RAG: ответы с источниками и цитатами
# ---------------------------------------------------------------------------

class AnswerConfig(BaseModel):
    """Конфигурация grounded-ответа (retrieval + генерация + два gate)."""

    query_rewrite: bool = False
    query_rewrite_model: Optional[str] = None

    initial_top_k: int = Field(default=20, ge=1, le=500)
    final_top_k: int = Field(default=5, ge=1, le=100)

    enable_filter: bool = True
    similarity_threshold: float = Field(default=0.65, ge=0.0, le=1.0)

    enable_reranker: bool = True
    reranker: Literal["heuristic", "cross_encoder", "similarity"] = "heuristic"
    reranker_model: Optional[str] = None

    # Generative layer
    answer_model: Optional[str] = None

    # Gates
    answer_relevance_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    grounding_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    min_supporting_chunks: int = Field(default=1, ge=0, le=100)

    @model_validator(mode="after")
    def _check(self) -> "AnswerConfig":
        if self.initial_top_k < self.final_top_k:
            raise ValueError("initial_top_k должен быть не меньше final_top_k")
        return self


class RagAnswerRequest(BaseModel):
    collection_id: Optional[str] = None
    index_id: Optional[str] = None
    strategy: Optional[Literal["fixed_size", "structural"]] = None
    query: str = Field(min_length=1, max_length=QUERY_MAX_LENGTH)
    config: AnswerConfig = Field(default_factory=AnswerConfig)


class AnswerLLMClaim(BaseModel):
    """Утверждение из структурного ответа LLM (LLM указывает только chunk_id)."""

    text: str = Field(min_length=1)
    chunk_ids: List[str] = Field(default_factory=list)


class AnswerLLMOutput(BaseModel):
    """Строгая JSON-схема, которую обязан вернуть generative LLM.

    LLM НЕ возвращает текст цитат и источников — только chunk_id.
    Источники, цитаты и их текст формирует backend из реальных чанков.
    """

    answer: str = ""
    claims: List[AnswerLLMClaim] = Field(default_factory=list)
    insufficient_context: bool = False


class AnswerSource(BaseModel):
    source: str
    section: Optional[str] = None
    chunk_id: str
    title: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    symbol_name: Optional[str] = None


class AnswerCitation(BaseModel):
    source: str
    section: Optional[str] = None
    chunk_id: str
    quote: str
    page_start: Optional[int] = None
    page_end: Optional[int] = None


class AnswerClaim(BaseModel):
    text: str
    chunk_ids: List[str] = Field(default_factory=list)
    grounded: bool
    grounding_score: float = 0.0


class GroundingInfo(BaseModel):
    grounded: bool
    grounding_score: float = 0.0
    claims_total: int = 0
    claims_supported: int = 0


class RagAnswerResponse(BaseModel):
    id: Optional[str] = None
    status: str  # answered|insufficient_context|grounding_failed
    answer: str
    sources: List[AnswerSource] = Field(default_factory=list)
    citations: List[AnswerCitation] = Field(default_factory=list)
    claims: List[AnswerClaim] = Field(default_factory=list)
    grounding: GroundingInfo = Field(default_factory=GroundingInfo)
    retrieval: Dict[str, Any] = Field(default_factory=dict)
    latency: Dict[str, Any] = Field(default_factory=dict)
