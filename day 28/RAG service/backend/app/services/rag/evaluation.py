"""Evaluation: датасеты, запуски сравнения режимов, эксперименты, экспорт."""

from __future__ import annotations

import csv
import io
import json
import time
from typing import Any, Dict, List, Optional

from ...schemas.rag import (
    EvalDatasetOut,
    EvalRunOut,
    ExperimentOut,
    RetrievalConfig,
)
from ...utils.common import utc_now_iso
from ...utils.errors import ConflictError, NotFoundError
from ...utils.ids import new_id
from ...utils.logging import get_logger
from .. import runtime
from . import repo
from .metrics import aggregate_metrics, compute_metrics, prediction_keys, relevant_keys
from .pipeline import RetrievalPipeline

logger = get_logger(__name__)

# Способы сравнения: имя → переопределения RetrievalConfig
MODE_WAYS: Dict[str, Dict[str, Any]] = {
    "baseline": {"query_rewrite": False, "enable_filter": False, "enable_reranker": False},
    "filter": {"enable_filter": True, "enable_reranker": False, "query_rewrite": False},
    "rerank": {"enable_reranker": True, "query_rewrite": False},
    "rewrite": {"query_rewrite": True, "enable_filter": False, "enable_reranker": False},
    "rewrite_rerank": {"query_rewrite": True, "enable_reranker": True, "enable_filter": False},
    "full": {"query_rewrite": True, "enable_filter": True, "enable_reranker": True},
}

MODE_LABELS = {
    "baseline": "Baseline",
    "filter": "Similarity Filter",
    "rerank": "Reranking",
    "rewrite": "Query Rewrite",
    "rewrite_rerank": "Rewrite + Rerank",
    "full": "Rewrite + Filter + Rerank",
}
ALL_MODES = list(MODE_WAYS.keys())


def _latency_avg(rows: List[dict], stage: str) -> float:
    vals = [r.get("latency", {}).get(stage) for r in rows]
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def _technical_stats(rows: List[dict]) -> Dict[str, Any]:
    """Технические показатели БЕЗ ground truth — это не «качество»."""
    items = [it for r in rows for it in r.get("items", [])]
    sims = [it["retrieval_score"] for it in items]
    rrk = [it["reranker_score"] for it in items if it.get("reranker_score") is not None]
    return {
        "avg_candidates": round(sum(len(r.get("items", [])) for r in rows) / len(rows), 2) if rows else 0,
        "avg_filtered": round(
            sum(r.get("filtering", {}).get("filtered", 0) for r in rows) / len(rows), 2
        ) if rows else 0,
        "avg_similarity": round(sum(sims) / len(sims), 4) if sims else 0.0,
        "avg_reranker_score": round(sum(rrk) / len(rrk), 4) if rrk else None,
    }


def run_mode(
    pipeline: RetrievalPipeline,
    mode: str,
    base_config: RetrievalConfig,
    questions: List[dict],
    collection_id: Optional[str],
    index_id: Optional[str],
    strategy: Optional[str],
    final_k: int,
) -> Dict[str, Any]:
    """Прогнать один режим по всем вопросам датасета, вернуть метрики и latency."""
    overrides = MODE_WAYS[mode]
    cfg = base_config.model_copy(update={**overrides})
    cfg.initial_top_k = max(cfg.initial_top_k, cfg.final_top_k)

    per_question: List[dict] = []
    latency_rows: List[dict] = []
    for item in questions:
        q = item["question"]
        t0 = time.perf_counter()
        try:
            result = pipeline.run(q, cfg, collection_id=collection_id, index_id=index_id, strategy=strategy)
        except Exception as e:  # noqa: BLE001
            per_question.append({
                "question": q, "error": str(e),
                "predicted": [], "relevant": relevant_keys(item), "metrics": None,
            })
            latency_rows.append({"latency": {"total_ms": (time.perf_counter() - t0) * 1000}})
            logger.warning("experiment_failed mode=%s query_len=%d error=%s", mode, len(q), type(e).__name__)
            continue
        predicted = [
            key
            for it in result["final"]["results"]
            for key in prediction_keys(it.get("source", ""), it.get("section"), it.get("chunk_id", ""))
        ]
        relevant = relevant_keys(item)
        metrics = compute_metrics(predicted, relevant, k=final_k)
        per_question.append({
            "question": q,
            "rewritten_query": result.get("rewritten_query"),
            "predicted_chunks": [it.get("chunk_id") for it in result["final"]["results"]],
            "predicted": predicted,
            "relevant": relevant,
            "retrieval": {k: result.get("retrieval", {}).get(k) for k in ("candidates", "initial_top_k")},
            "filtering": {k: result.get("filtering", {}).get(k) for k in ("passed", "filtered")},
            "metrics": metrics,
            "items": result.get("items", []),
        })
        latency_rows.append({"latency": result.get("latency", {})})

    metrics_agg = aggregate_metrics(
        (pq["metrics"] for pq in per_question if pq.get("metrics")), k=final_k
    )
    tech = _technical_stats([pq for pq in per_question if not pq.get("error")])
    # «N/A вместо случайных чисел»: считаем hit@K при наличии ground truth
    has_gt = any(bool(pq["relevant"]) for pq in per_question)
    out = {
        "mode": mode,
        "label": MODE_LABELS.get(mode, mode),
        "per_question": per_question,
        "metrics": metrics_agg,
        "technical": tech,
        "has_ground_truth": has_gt,
        "errors": sum(1 for pq in per_question if pq.get("error")),
        "latency": {
            "query_rewrite_ms": _latency_avg(latency_rows, "query_rewrite_ms"),
            "embedding_ms": _latency_avg(latency_rows, "embedding_ms"),
            "retrieval_ms": _latency_avg(latency_rows, "retrieval_ms"),
            "filtering_ms": _latency_avg(latency_rows, "filtering_ms"),
            "reranking_ms": _latency_avg(latency_rows, "reranking_ms"),
            "total_ms": _latency_avg(latency_rows, "total_ms"),
        },
    }
    return out


def run_evaluation(
    dataset_id: str,
    modes: List[str],
    base_config: RetrievalConfig,
    collection_id: Optional[str],
    index_id: Optional[str],
    strategy: Optional[str],
    name: str = "",
    pipeline_inst: Optional[RetrievalPipeline] = None,
) -> dict:
    """Запуск сравнения всех мод по датасету (синхронно, для локального окружения)."""
    ds = repo.get_dataset(dataset_id)
    if ds is None:
        raise NotFoundError("Датасет не найден", code="dataset_not_found")
    items = json.loads(ds["items"])
    run_id = new_id("run")
    cfg_input = base_config.model_dump(mode="json")
    run = repo.create_run({
        "id": run_id, "dataset_id": dataset_id, "name": name or ds["name"],
        "status": "running",
        "collection_id": collection_id, "index_id": index_id,
        "config": {"modes": modes, "base_config": cfg_input},
    })
    pl = pipeline_inst or RetrievalPipeline()
    final_k = base_config.final_top_k
    modes = [m for m in modes if m in MODE_WAYS] or list(MODE_WAYS.keys())

    try:
        results = {
            mode: run_mode(pl, mode, base_config, items, collection_id, index_id, strategy, final_k)
            for mode in modes
        }
        metrics_table = {
            mode: {
                "k": final_k,
                "hit_at_k": r["metrics"]["hit_at_k"],
                "precision_at_k": r["metrics"]["precision_at_k"],
                "recall_at_k": r["metrics"]["recall_at_k"],
                "mrr": r["metrics"]["mrr"],
                "latency_ms": r["latency"]["total_ms"],
                "questions": r["metrics"]["questions"],
                "has_ground_truth": r["has_ground_truth"],
                "errors": r["errors"],
            }
            for mode, r in results.items()
        }
        latency_table = {
            mode: {
                "query_rewrite_ms": r["latency"]["query_rewrite_ms"],
                "embedding_ms": r["latency"]["embedding_ms"],
                "retrieval_ms": r["latency"]["retrieval_ms"],
                "filtering_ms": r["latency"]["filtering_ms"],
                "reranking_ms": r["latency"]["reranking_ms"],
                "total_ms": r["latency"]["total_ms"],
            }
            for mode, r in results.items()
        }
        update = {
            "status": "completed",
            "results": results,
            "metrics": metrics_table,
            "latency": latency_table,
            "finished_at": utc_now_iso(),
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("experiment_failed run=%s", run_id)
        update = {"status": "failed", "message": str(e), "finished_at": utc_now_iso()}
    repo.update_run(run_id, **update)
    return run_out(run_id)


def run_out(run_id: str) -> dict:
    row = repo.get_run(run_id)
    if row is None:
        raise NotFoundError("Запуск не найден", code="run_not_found")
    return {
        "id": row["id"], "dataset_id": row["dataset_id"], "name": row.get("name", ""),
        "status": row["status"],
        "collection_id": row.get("collection_id"), "index_id": row.get("index_id"),
        "config": json.loads(row["config"] or "{}"),
        "results": json.loads(row["results"]) if row.get("results") else None,
        "metrics": json.loads(row["metrics"]) if row.get("metrics") else None,
        "latency": json.loads(row["latency"]) if row.get("latency") else None,
        "message": row.get("message"),
        "created_at": row.get("created_at"), "finished_at": row.get("finished_at"),
    }


# ---------------------------------------------------------------------------
# Эксперименты (сохранение отдельных поисков)
# ---------------------------------------------------------------------------

def save_experiment(payload: dict) -> dict:
    cfg = payload.get("config") or {}
    if isinstance(cfg, RetrievalConfig):
        cfg_dict = cfg.model_dump(mode="json")
    elif isinstance(cfg, dict):
        cfg_dict = json.loads(json.dumps(cfg))
    else:
        cfg_dict = {}
    result = payload.get("result") or {}
    rec = {
        "id": new_id("exp"),
        "name": payload.get("name") or "Эксперимент",
        "run_id": payload.get("run_id"),
        "dataset_id": payload.get("dataset_id"),
        "collection_id": payload.get("collection_id") or result.get("retrieval", {}).get("collection_id"),
        "index_id": payload.get("index_id") or result.get("retrieval", {}).get("index_id"),
        "strategy": payload.get("strategy") or result.get("retrieval", {}).get("strategy"),
        "query": payload.get("query") or result.get("original_query", ""),
        "config": cfg_dict,
        "metrics": payload.get("metrics") or _metrics_from_result(result),
        "latency": payload.get("latency") or result.get("latency"),
        "result": result,
    }
    row = repo.create_experiment(rec)
    return experiment_out(row)


def _metrics_from_result(result: dict) -> dict:
    """Технический отчёт по одному поиску (без ground truth — не «качество»)."""
    items = result.get("items") or []
    sims = [it.get("retrieval_score") for it in items if it.get("retrieval_score") is not None]
    rrk = [it.get("reranker_score") for it in items if it.get("reranker_score") is not None]
    return {
        "technical": {
            "candidates": result.get("retrieval", {}).get("candidates", len(items)),
            "filtered": result.get("filtering", {}).get("filtered", 0),
            "passed": result.get("filtering", {}).get("passed", len(items)),
            "avg_similarity": round(sum(sims) / len(sims), 4) if sims else 0.0,
            "avg_reranker_score": round(sum(rrk) / len(rrk), 4) if rrk else None,
        }
    }


def experiment_out(row: dict) -> dict:
    return {
        "id": row["id"], "name": row["name"],
        "collection_id": row.get("collection_id"), "index_id": row.get("index_id"),
        "strategy": row.get("strategy"), "query": row["query"],
        "run_id": row.get("run_id"), "dataset_id": row.get("dataset_id"),
        "config": json.loads(row["config"] or "{}"),
        "metrics": json.loads(row["metrics"]) if row.get("metrics") else None,
        "latency": json.loads(row["latency"]) if row.get("latency") else None,
        "result": json.loads(row["result"] or "{}"),
        "created_at": row.get("created_at"),
    }


# ---------------------------------------------------------------------------
# Экспорт
# ---------------------------------------------------------------------------

def export_experiment_json(experiment_id: str) -> dict:
    row = repo.get_experiment(experiment_id)
    if row is None:
        raise NotFoundError("Эксперимент не найден", code="experiment_not_found")
    return {
        "experiment_id": row["id"],
        "name": row["name"],
        "created_at": row.get("created_at"),
        "query": row["query"],
        "configuration": json.loads(row["config"] or "{}"),
        "metrics": json.loads(row["metrics"]) if row.get("metrics") else None,
        "latency": json.loads(row["latency"]) if row.get("latency") else None,
        "results": json.loads(row["result"] or "{}"),
    }


DEMO_DATASET_ITEMS = [
    {"question": "Что такое RAG и зачем он нужен?",
     "expected_sources": ["rag_principles.md"], "expected_sections": ["Что такое RAG"], "relevant_chunk_ids": []},
    {"question": "Какие этапы входят в индексацию для RAG?",
     "expected_sources": ["rag_principles.md"], "expected_sections": ["Основные этапы RAG"], "relevant_chunk_ids": []},
    {"question": "Почему качество индексации влияет на результат RAG?",
     "expected_sources": ["rag_principles.md"], "expected_sections": ["Зачем нужна индексация", "Компромиссы при выборе стратегии"], "relevant_chunk_ids": []},
    {"question": "Что такое эмбеддинг текста?",
     "expected_sources": ["embeddings_guide.md"], "expected_sections": ["Что такое эмбеддинг"], "relevant_chunk_ids": []},
    {"question": "Чем косинусное сходство отличается от евклидова расстояния?",
     "expected_sources": ["embeddings_guide.md"], "expected_sections": ["Метрики сходства"], "relevant_chunk_ids": []},
    {"question": "Зачем нормализовать векторы перед поиском?",
     "expected_sources": ["embeddings_guide.md"], "expected_sections": ["Почему нужна нормализация"], "relevant_chunk_ids": []},
    {"question": "Что такое FAISS и для чего он используется?",
     "expected_sources": ["faiss_and_search.md"], "expected_sections": ["Введение"], "relevant_chunk_ids": []},
    {"question": "Как хранятся координаты векторов и метаданных чанков в индексе?",
     "expected_sources": ["faiss_and_search.md"], "expected_sections": ["Координация индекс и метаданные"], "relevant_chunk_ids": []},
    {"question": "Какие ограничения есть у векторного поиска?",
     "expected_sources": ["faiss_and_search.md"], "expected_sections": ["Ограничения"], "relevant_chunk_ids": []},
    {"question": "Как устроен класс FixedSizeChunker в примере кода?",
     "expected_sources": ["example_rag_pipeline.py"], "expected_sections": [], "relevant_chunk_ids": []},
]


def seed_demo_dataset() -> EvalDatasetOut:
    """Создать демонстрационный evaluation датасет (по demo-корпусу), если его нет."""
    existing = [d for d in repo.list_datasets() if d["name"] == "Демо-датасет (demo corpus)"]
    if existing:
        return EvalDatasetOut(**json.loads(json.dumps(_row_out(existing[0]))))
    row = repo.create_dataset({
        "id": new_id("ds"), "name": "Демо-датасет (demo corpus)",
        "description": "10 вопросов к демонстрационному корпусу (кнопка «Загрузить демонстрационные документы»).",
        "items": DEMO_DATASET_ITEMS,
    })
    return _row_out(row)


def _row_out(row: dict) -> EvalDatasetOut:
    return EvalDatasetOut(
        id=row["id"], name=row["name"], description=row.get("description") or "",
        items=json.loads(row["items"] or "[]"),
        created_at=row.get("created_at") or "", updated_at=row.get("updated_at") or "",
    )


def export_run_json(run_id: str) -> dict:
    return run_out(run_id)


def export_run_csv(data: dict) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["run_id", "mode", "question", "hit@k", "precision@k", "recall@k",
                     "mrr", "candidates", "filtered", "total_ms"])
    results = data.get("results") or {}
    for mode, mode_res in results.items():
        for pq in mode_res.get("per_question") or []:
            m = pq.get("metrics") or {}
            validation = {}
            writer.writerow([
                data.get("id"), mode, pq.get("question"),
                m.get("hit_at_k"), m.get("precision_at_k"), m.get("recall_at_k"), m.get("mrr"),
                (pq.get("retrieval") or {}).get("candidates"),
                (pq.get("filtering") or {}).get("filtered"),
                None,
            ])
    if not any((data.get("results") or {}).values()):
        writer.writerow(["No results"])
    return buf.getvalue()


def export_experiment_csv(experiment_id: str) -> str:
    data = export_experiment_json(experiment_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["experiment_id", "name", "created_at", "query", "mode/config",
                     "final_rank", "chunk_id", "source", "section", "retrieval_score",
                     "reranker_score", "status"])
    items = (data.get("results") or {}).get("items") or []
    cfg = data.get("configuration") or {}
    for it in items:
        writer.writerow([
            data["experiment_id"], data["name"], data.get("created_at"), data["query"],
            json.dumps(cfg, ensure_ascii=False),
            it.get("final_rank"), it.get("chunk_id"), it.get("source"), it.get("section"),
            it.get("retrieval_score"), it.get("reranker_score"), it.get("status"),
        ])
    if not items:
        writer.writerow(["No results"])
    return buf.getvalue()


def evaluate_experiment_metrics(experiment_id: str, relevant: List[str], k: int) -> dict:
    """Вычислить метрики качества сохранённого эксперимента по явному ground truth."""
    row = repo.get_experiment(experiment_id)
    if row is None:
        raise NotFoundError("Эксперимент не найден", code="experiment_not_found")
    result = json.loads(row["result"] or "{}")
    predicted = []
    for it in result.get("final", {}).get("results", []):
        predicted.extend(prediction_keys(it.get("source", ""), it.get("section"), it.get("chunk_id", "")))
    return compute_metrics(predicted, relevant, k=k)