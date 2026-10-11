"""API модуля «Reranking & Filtering»: pipeline, evaluation, эксперименты."""

from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, Query, Response, status

from ..repositories import collections_repo
from ..schemas.rag import (
    EvalDatasetCreate,
    EvalDatasetOut,
    EvalRunOut,
    EvalRunRequest,
    ExperimentCreate,
    FilterRequest,
    FilterResponse,
    QueryRewriteRequest,
    QueryRewriteResponse,
    RagSearchRequest,
    RagAnswerRequest,
    RerankersStatus,
    RerankRequest,
    RerankResponse,
    RerankerStatus,
    RetrieveRequest,
    RetrievalConfig,
)
from ..schemas.common import MessageResponse
from ..utils.errors import NotFoundError
from ..utils.logging import get_logger
from ..services import runtime
from ..services.rag import evaluation as ev
from ..services.rag.metrics import relevant_keys
from ..services.rag.pipeline import pipeline as default_pipeline
from ..services.rag.query_rewriter import rewriter_holder
from ..services.rag import answer_eval
from ..services.rag import answer_repo
from ..services.rag.rag_service import answer_service
from ..services.rag.rerankers import RerankerUnavailable, build_reranker, rerankers_status
from ..utils.ids import new_id

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["RAG: Reranking & Filtering"])

STRATEGIES = ("fixed_size", "structural")


def _resolve_strategy(strategy: Optional[str], collection_id: Optional[str]) -> str:
    if strategy:
        return strategy
    if collection_id:
        recs = collections_repo.list_indexes(collection_id)
        if recs:
            return recs[0]["strategy"]
    return "structural"


# ---------------------------------------------------------------------------
# Query rewrite
# ---------------------------------------------------------------------------

@router.post("/rag/query-rewrite", summary="Переписать запрос через локальную LLM")
def query_rewrite(req: QueryRewriteRequest) -> QueryRewriteResponse:
    settings = runtime.effective_settings()
    model = req.model or settings.query_rewrite_model
    rw = rewriter_holder.get()
    res = rw.rewrite(req.query, model=model)
    return QueryRewriteResponse(
        original_query=req.query, rewritten_query=res.rewritten,
        model=res.model, latency_ms=res.latency_ms,
    )


# ---------------------------------------------------------------------------
# Отдельные этапы (для отладки)
# ---------------------------------------------------------------------------

@router.post("/rag/retrieve", summary="Только этап retrieval (FAISS)")
def rag_retrieve(req: RetrieveRequest) -> dict:
    strategy = _resolve_strategy(req.strategy, req.collection_id)
    result = default_pipeline.run(
        req.query,
        config=RetrievalConfig(
            initial_top_k=req.top_k, final_top_k=req.top_k,
            enable_filter=False, enable_reranker=False,
        ),
        collection_id=req.collection_id, index_id=req.index_id, strategy=strategy,
    )
    return {
        "query": req.query,
        "retrieval": result["retrieval"],
        "results": result["items"],
        "latency": result["latency"],
    }


@router.post("/rag/filter", summary="Фильтрация по similarity (порог включительно)")
def rag_filter(req: FilterRequest) -> FilterResponse:
    th = req.threshold
    kept = [i for i, s in enumerate(req.scores) if s >= th]  # правило: >= threshold → оставлен
    return FilterResponse(
        threshold=th, passed=len(kept), filtered=len(req.scores) - len(kept), kept_positions=kept,
    )


@router.post("/rag/rerank", summary="Реранкинг кандидатов по запросу")
def rag_rerank(req: RerankRequest) -> RerankResponse:
    settings = runtime.effective_settings()
    try:
        reranker = build_reranker(
            req.reranker, model=req.model or settings.reranker_model, base_scores=req.base_scores,
        )
        scores = reranker.rerank(req.query, req.documents)
    except RerankerUnavailable as e:
        from ..utils.errors import ConflictError

        raise ConflictError(
            f"{e} Установите модель (или выберите heuristic/отключите реранкинг).",
            code="reranker_unavailable",
        )
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    return RerankResponse(
        reranker=req.reranker, model=getattr(reranker, "model", None),
        scores=[round(float(s), 6) for s in scores], reranked_positions=order,
    )


@router.get("/rag/rerankers/status", summary="Статусы реранкеров", response_model=RerankersStatus)
def rerankers_status_route() -> RerankersStatus:
    settings = runtime.effective_settings()
    st = rerankers_status(settings.reranker_model)
    return RerankersStatus(
        heuristic=RerankerStatus(reranker="heuristic", model=None, **{k: st["heuristic"].get(k) for k in ("available", "reason", "install_hint")}),
        cross_encoder=RerankerStatus(reranker="cross_encoder", model=settings.reranker_model, **{k: st["cross_encoder"].get(k) for k in ("available", "reason", "install_hint")}),
        similarity=RerankerStatus(reranker="similarity", model=None, **{k: st["similarity"].get(k) for k in ("available", "reason", "install_hint")}),
        default_reranker=settings.reranker_type,
        default_model=settings.reranker_model,
    )


# ---------------------------------------------------------------------------
# Основной pipeline
# ---------------------------------------------------------------------------

@router.post("/rag/search", summary="Полный pipeline: rewrite → retrieval → filter → rerank → final")
def rag_search(req: RagSearchRequest) -> dict:
    strategy = _resolve_strategy(req.strategy, req.collection_id)
    try:
        result = default_pipeline.run(
            req.query, req.config,
            collection_id=req.collection_id, index_id=req.index_id, strategy=strategy,
        )
    except Exception as e:
        logger.warning("rag_search failed: %s", e)
        raise
    result["retrieval"]["strategy"] = strategy
    return result


# ---------------------------------------------------------------------------
# Evaluation datasets & runs
# ---------------------------------------------------------------------------

def _dataset_out(row: dict) -> EvalDatasetOut:
    return EvalDatasetOut(
        id=row["id"], name=row["name"], description=row.get("description") or "",
        items=json.loads(row["items"] or "[]"),
        created_at=row.get("created_at") or "", updated_at=row.get("updated_at") or "",
    )


@router.get("/evaluation/datasets", summary="Список evaluation датасетов", response_model=List[EvalDatasetOut])
def list_datasets() -> List[EvalDatasetOut]:
    return [_dataset_out(r) for r in ev.repo.list_datasets()]


@router.post("/evaluation/datasets", summary="Создать evaluation датасет", status_code=status.HTTP_201_CREATED)
def create_dataset(req: EvalDatasetCreate) -> EvalDatasetOut:
    row = ev.repo.create_dataset({
        "id": new_id("ds"), "name": req.name, "description": req.description,
        "items": [it.model_dump() for it in req.items],
    })
    return _dataset_out(row)


@router.get("/evaluation/datasets/{dataset_id}", summary="Датасет по id", response_model=EvalDatasetOut)
def get_dataset(dataset_id: str) -> EvalDatasetOut:
    row = ev.repo.get_dataset(dataset_id)
    if row is None:
        raise NotFoundError("Датасет не найден", code="dataset_not_found")
    return _dataset_out(row)


@router.delete("/evaluation/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: str) -> None:
    if not ev.repo.delete_dataset(dataset_id):
        raise NotFoundError("Датасет не найден", code="dataset_not_found")


@router.post("/evaluation/datasets/demo", summary="Создать демонстрационный evaluation датасет")
def demo_dataset() -> EvalDatasetOut:
    from ..services.rag.evaluation import seed_demo_dataset

    return seed_demo_dataset()


@router.post("/evaluation/datasets/{dataset_id}/run", summary="Прогнать сравнение режимов по датасету")
def run_dataset(dataset_id: str, req: EvalRunRequest) -> dict:
    strategy = _resolve_strategy(req.strategy, req.collection_id)
    return ev.run_evaluation(
        dataset_id=dataset_id,
        modes=req.modes,
        base_config=req.base_config,
        collection_id=req.collection_id,
        index_id=req.index_id,
        strategy=strategy,
        name=req.name,
    )


@router.get("/evaluation/runs", summary="Список запусков сравнения")
def list_runs(limit: int = Query(default=50, ge=1, le=200)) -> List[dict]:
    return [ev.run_out(r["id"]) for r in ev.repo.list_runs(limit) if r.get("status")]


@router.get("/evaluation/runs/{run_id}", summary="Результат запуска сравнения", response_model=EvalRunOut)
def get_run(run_id: str) -> dict:
    return ev.run_out(run_id)


@router.get("/evaluation/runs/{run_id}/export", summary="Экспорт запуска (JSON или CSV)")
def export_run(run_id: str, format: str = Query(default="json", pattern="^(json|csv)$")) -> Response:
    data = ev.export_run_json(run_id)
    if format == "csv":
        return Response(
            content=ev.export_run_csv(data),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="run-{run_id}.csv"'},
        )
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="run-{run_id}.json"'},
    )


# ---------------------------------------------------------------------------
# Эксперименты
# ---------------------------------------------------------------------------

@router.get("/experiments", summary="Список сохранённых экспериментов")
def list_experiments(limit: int = Query(default=200, ge=1, le=500)) -> List[dict]:
    return [ev.experiment_out(r) for r in ev.repo.list_experiments(limit)]


@router.post("/experiments", summary="Сохранить эксперимент", status_code=status.HTTP_201_CREATED)
def save_experiment(req: ExperimentCreate) -> dict:
    return ev.save_experiment(req.model_dump())


@router.get("/experiments/{experiment_id}", summary="Эксперимент по id")
def get_experiment(experiment_id: str) -> dict:
    row = ev.repo.get_experiment(experiment_id)
    if row is None:
        raise NotFoundError("Эксперимент не найден", code="experiment_not_found")
    return ev.experiment_out(row)


@router.delete("/experiments/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_experiment(experiment_id: str) -> None:
    if not ev.repo.delete_experiment(experiment_id):
        raise NotFoundError("Эксперимент не найден", code="experiment_not_found")


@router.get("/experiments/{experiment_id}/export", summary="Экспорт эксперимента (JSON или CSV)")
def export_experiment(experiment_id: str, format: str = Query(default="json", pattern="^(json|csv)$")) -> Response:
    if format == "csv":
        return Response(
            content=ev.export_experiment_csv(experiment_id),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="experiment-{experiment_id}.csv"'},
        )
    data = ev.export_experiment_json(experiment_id)
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="experiment-{experiment_id}.json"'},
    )


@router.post("/experiments/{experiment_id}/compare", summary="Сравнить два эксперимента")
def compare_experiments(experiment_id: str, other_id: str = Query(...)) -> dict:
    a = ev.repo.get_experiment(experiment_id)
    b = ev.repo.get_experiment(other_id)
    if a is None or b is None:
        raise NotFoundError("Эксперимент не найден", code="experiment_not_found")
    return {
        "current": ev.experiment_out(a),
        "compared": ev.experiment_out(b),
        "note": (
            "Сравнение показывает фактические результаты двух запусков. "
            "Вывод о «лучшем» режиме делается только по метрикам evaluation."
        ),
    }

# ---------------------------------------------------------------------------
# Grounded RAG: ответы с источниками и цитатами
# ---------------------------------------------------------------------------

@router.post("/rag/answer", summary="Grounded-ответ: retrieval → relevance gate → LLM → grounding → citations")
def rag_answer(req: RagAnswerRequest) -> dict:
    strategy = _resolve_strategy(req.strategy, req.collection_id)
    return answer_service.answer(
        req.query, req.config,
        collection_id=req.collection_id, index_id=req.index_id, strategy=strategy,
    )


@router.get("/rag/answers", summary="История grounded-ответов")
def list_answers(limit: int = Query(default=100, ge=1, le=500)) -> List[dict]:
    return [answer_repo.answer_out(r) for r in answer_repo.list_answers(limit)]


@router.get("/rag/answers/{answer_id}", summary="Grounded-ответ по id")
def get_answer(answer_id: str) -> dict:
    row = answer_repo.get_answer(answer_id)
    if row is None:
        raise NotFoundError("Ответ не найден", code="answer_not_found")
    return answer_repo.answer_out(row)


@router.delete("/rag/answers/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_answer(answer_id: str) -> None:
    if not answer_repo.delete_answer(answer_id):
        raise NotFoundError("Ответ не найден", code="answer_not_found")


# ---------------------------------------------------------------------------
# Grounded RAG Evaluation (10 вопросов)
# ---------------------------------------------------------------------------

@router.post("/rag/evaluation/dataset", summary="Создать/получить датасет grounded-оценки (10 вопросов)")
def seeded_grounded_dataset() -> EvalDatasetOut:
    return answer_eval.seed_grounded_dataset()


@router.post("/rag/evaluation/run", summary="Прогнать grounded-оценку по датасету")
def run_grounded_eval(req: EvalRunRequest) -> dict:
    strategy = _resolve_strategy(req.strategy, req.collection_id)
    from ..schemas.rag import AnswerConfig
    cfg = AnswerConfig(
        query_rewrite=req.base_config.query_rewrite,
        query_rewrite_model=req.base_config.query_rewrite_model,
        initial_top_k=req.base_config.initial_top_k,
        final_top_k=req.base_config.final_top_k,
        enable_filter=req.base_config.enable_filter,
        similarity_threshold=req.base_config.similarity_threshold,
        enable_reranker=req.base_config.enable_reranker,
        reranker=req.base_config.reranker,
        reranker_model=req.base_config.reranker_model,
    )
    return answer_eval.run_grounded_eval(
        dataset_id=req.dataset_id, collection_id=req.collection_id, index_id=req.index_id,
        strategy=strategy, config=cfg, name=req.name,
    )


@router.get("/rag/evaluation/runs", summary="Список запусков grounded-оценки")
def list_answer_eval_runs(limit: int = Query(default=50, ge=1, le=200)) -> List[dict]:
    return [answer_repo.eval_answer_run_out(r) for r in answer_repo.list_eval_answer_runs(limit)]


@router.get("/rag/evaluation/runs/{run_id}", summary="Результат запуска grounded-оценки")
def get_answer_eval_run(run_id: str) -> dict:
    row = answer_repo.get_eval_answer_run(run_id)
    if row is None:
        raise NotFoundError("Запуск grounded-оценки не найден", code="eval_run_not_found")
    return answer_repo.eval_answer_run_out(row)
