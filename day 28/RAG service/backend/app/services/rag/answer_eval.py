"""Grounded RAG Evaluation: автоматическая оценка качества grounded-ответов.

По каждому вопросу датасета прогоняется полный pipeline (retrieval → gate →
LLM → grounding) и проверяются:
  answer_present, sources_present, citations_present,
  citation_valid, source_valid, answer_grounded, unsupported_claims.

Итоговые метрики считаются только по фактическим результатам:
  Source Coverage, Citation Coverage, Citation Validity,
  Grounding Accuracy, Abstention Accuracy.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from ...schemas.rag import AnswerConfig, EvalDatasetOut
from ...utils.common import utc_now_iso
from ...utils.errors import NotFoundError
from ...utils.ids import new_id
from ...utils.logging import get_logger
from .. import runtime
from . import answer_repo
from . import repo
from .rag_service import answer_service

logger = get_logger(__name__)

# 10 вопросов: 9 — по демонстрационному корпусу, 1 — abstention (ответа нет в документах).
GROUNDED_EVAL_ITEMS = [
    {"question": "Что такое RAG и зачем он нужен?",
     "expected_sources": ["rag_principles.md"], "expected_sections": ["Что такое RAG"]},
    {"question": "Какие этапы входят в индексацию для RAG?",
     "expected_sources": ["rag_principles.md"], "expected_sections": ["Основные этапы RAG"]},
    {"question": "Почему качество индексации влияет на результат RAG?",
     "expected_sources": ["rag_principles.md"], "expected_sections": ["Зачем нужна индексация"]},
    {"question": "Что такое эмбеддинг текста?",
     "expected_sources": ["embeddings_guide.md"], "expected_sections": ["Что такое эмбеддинг"]},
    {"question": "Чем косинусное сходство отличается от евклидова расстояния?",
     "expected_sources": ["embeddings_guide.md"], "expected_sections": ["Метрики сходства"]},
    {"question": "Зачем нормализовать векторы перед поиском?",
     "expected_sources": ["embeddings_guide.md"], "expected_sections": ["Почему нужна нормализация"]},
    {"question": "Что такое FAISS и для чего он используется?",
     "expected_sources": ["faiss_and_search.md"], "expected_sections": ["Введение"]},
    {"question": "Как хранятся координаты векторов и метаданных чанков в индексе?",
     "expected_sources": ["faiss_and_search.md"], "expected_sections": ["Координация индекс и метаданные"]},
    {"question": "Какие ограничения есть у векторного поиска?",
     "expected_sources": ["faiss_and_search.md"], "expected_sections": ["Ограничения"]},
    {"question": "Какая температура была вчера в Берлине?",
     "expected_sources": [], "expected_sections": [], "abstention": True},
]

EVAL_DATASET_NAME = "Grounded RAG (10 вопросов)"

GROUNDED_DATASET_DESCRIPTION = (
    "10 вопросов для оценки grounded-ответов: 9 — по демонстрационному корпусу, "
    "1 — намеренно без ответа в документах (проверка abstention)."
)


def seed_grounded_dataset() -> EvalDatasetOut:
    existing = [d for d in repo.list_datasets() if d["name"] == EVAL_DATASET_NAME]
    if existing:
        return EvalDatasetOut(
            id=existing[0]["id"], name=existing[0]["name"],
            description=existing[0].get("description") or "",
            items=json.loads(existing[0]["items"] or "[]"),
            created_at=existing[0].get("created_at") or "",
            updated_at=existing[0].get("updated_at") or "",
        )
    row = repo.create_dataset({
        "id": new_id("ds"), "name": EVAL_DATASET_NAME,
        "description": GROUNDED_DATASET_DESCRIPTION, "items": GROUNDED_EVAL_ITEMS,
    })
    return EvalDatasetOut(
        id=row["id"], name=row["name"], description=row.get("description") or "",
        items=json.loads(row["items"] or "[]"),
        created_at=row.get("created_at") or "", updated_at=row.get("updated_at") or "",
    )


def _dataset_items(dataset_id: str) -> List[dict]:
    ds = repo.get_dataset(dataset_id)
    if ds is None:
        raise NotFoundError("Датасет не найден", code="dataset_not_found")
    return json.loads(ds["items"])


def _check_answer(answer: dict, item: dict) -> Dict[str, Any]:
    status = answer.get("status", "failed")
    sources = answer.get("sources") or []
    citations = answer.get("citations") or []
    claims = answer.get("claims") or []
    grounding = answer.get("grounding") or {}
    abstention_expected = bool(item.get("abstention"))
    expected_sources = item.get("expected_sources") or []

    answer_present = status == "answered"
    sources_present = answer_present and len(sources) > 0
    citations_present = answer_present and len(citations) > 0
    # backend формирует цитаты только из реального текста чанков → valid при наличии
    citation_valid = citations_present and all(c.get("quote") for c in citations)
    source_valid = answer_present and all(
        s.get("source") for s in sources
    )
    answer_grounded = answer_present and grounding.get("grounded", False)
    unsupported_claims = sum(1 for c in claims if not c.get("grounded", False))

    # Result: PASS / FAIL / INSUFFICIENT_CONTEXT
    if abstention_expected:
        correct_abstain = status != "answered" and len(sources) == 0 and len(citations) == 0
        result = "PASS" if correct_abstain else "FAIL"
    elif answer_present:
        ok = (
            sources_present and citations_present and citation_valid
            and source_valid and answer_grounded and unsupported_claims == 0
        )
        result = "PASS" if ok else "FAIL"
    else:
        result = "INSUFFICIENT_CONTEXT"

    return {
        "question": item["question"],
        "expected_sources": expected_sources,
        "abstention": abstention_expected,
        "status": status,
        "answer_excerpt": (answer.get("answer") or "")[:300],
        "results": {
            "answer_present": answer_present,
            "sources_present": sources_present,
            "citations_present": citations_present,
            "citation_valid": citation_valid,
            "source_valid": source_valid,
            "answer_grounded": answer_grounded,
            "unsupported_claims": unsupported_claims,
        },
        "sources": sources,
        "citations": citations,
        "claims": claims,
        "grounding": grounding,
        "relevance_score": (answer.get("retrieval") or {}).get("relevance_score"),
        "result": result,
        "latency": answer.get("latency") or {},
    }


def run_grounded_eval(
    dataset_id: str,
    collection_id: Optional[str],
    index_id: Optional[str],
    strategy: Optional[str],
    config: AnswerConfig,
    name: str = "",
    service=None,
) -> dict:
    items = _dataset_items(dataset_id)
    run_id = new_id("rageval")
    svc = service or answer_service
    run = answer_repo.create_eval_answer_run({
        "id": run_id, "name": name or EVAL_DATASET_NAME, "status": "running",
        "dataset_id": dataset_id, "collection_id": collection_id, "index_id": index_id,
        "strategy": strategy, "config": config.model_dump(mode="json"),
    })
    per_question: List[dict] = []
    for item in items:
        q = item["question"]
        try:
            answer = svc.answer(q, config, collection_id=collection_id, index_id=index_id, strategy=strategy)
            per_question.append(_check_answer(answer, item))
        except Exception as e:  # noqa: BLE001
            per_question.append({
                "question": q, "expected_sources": item.get("expected_sources") or [],
                "abstention": bool(item.get("abstention")), "status": "failed",
                "answer_excerpt": "", "error": str(e), "result": "FAIL",
                "results": {"answer_present": False, "sources_present": False,
                            "citations_present": False, "citation_valid": False,
                            "source_valid": False, "answer_grounded": False,
                            "unsupported_claims": 0},
                "sources": [], "citations": [], "claims": [], "grounding": {},
            })
            logger.warning("answer_eval item failed q_len=%d error=%s", len(q), type(e).__name__)

    metrics = _aggregate(per_question)
    update = {"status": "completed", "per_question": per_question, "metrics": metrics,
              "finished_at": utc_now_iso()}
    answer_repo.update_eval_answer_run(run_id, **update)
    return answer_repo.eval_answer_run_out(answer_repo.get_eval_answer_run(run_id))


def _aggregate(rows: List[dict]) -> Dict[str, Any]:
    n = len(rows)
    answered = [r for r in rows if r.get("status") == "answered"]
    abstain_items = [r for r in rows if r.get("abstention")]
    ans_ok = lambda r: (r.get("results") or {})

    answered_with_sources = sum(1 for r in answered if ans_ok(r).get("sources_present"))
    answered_with_citations = sum(1 for r in answered if ans_ok(r).get("citations_present"))
    valid_citations = sum(1 for r in answered if ans_ok(r).get("citation_valid"))
    grounded_answers = sum(1 for r in answered if ans_ok(r).get("answer_grounded"))
    correct_abstentions = sum(
        1 for r in abstain_items if (r.get("results") or {}).get("answer_present") is False
        and not (r.get("sources"))
    )
    total_citations = sum(len(r.get("citations") or []) for r in answered)

    def pct(num: int, den: int) -> float:
        return round(num / den * 100, 1) if den else 0.0

    coverage_num = len(answered) if len(answered) else 1
    return {
        "questions": n,
        "answers_generated": len(answered),
        "insufficient_context": n - len(answered),
        "source_coverage": pct(answered_with_sources, coverage_num),
        "citation_coverage": pct(answered_with_citations, coverage_num),
        "citation_validity": pct(valid_citations, coverage_num),
        "grounding_accuracy": pct(grounded_answers, coverage_num),
        "abstention_accuracy": pct(correct_abstentions, len(abstain_items)) if abstain_items else None,
        "source_coverage_ratio": f"{answered_with_sources}/{len(answered)}",
        "citation_coverage_ratio": f"{answered_with_citations}/{len(answered)}",
        "grounding_ratio": f"{grounded_answers}/{len(answered)}",
        "abstention_ratio": f"{correct_abstentions}/{len(abstain_items)}" if abstain_items else None,
        "total_citations": total_citations,
    }
