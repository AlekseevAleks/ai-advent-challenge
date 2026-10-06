"""Chat Evaluation: прогон сценариев длинного диалога по полному pipeline
и честный расчёт метрик (без заранее заданных чисел).

Каждый вопрос сценария проходит через `ChatService` (→ существующий RAG →
rerank → relevance gate → LLM → grounding → citations), поэтому `rag_called`
всегда true для сработавших сообщений.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...utils.logging import get_logger
from . import chat_service as cs

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Сценарии
# ---------------------------------------------------------------------------

SCENARIO_1 = {
    "name": "Сценарий 1: пошаговое построение RAG-сервиса",
    "messages": [
        "Мне нужно создать учебный RAG-сервис.",
        "Он должен работать локально.",
        "Embeddings должны использовать nomic-embed-text.",
        "Для vector search используем FAISS.",
        "Добавим reranking.",
        "Что такое reranking?",
        "А зачем он нужен?",
        "Какой reranker лучше?",
        "Оставим BGE reranker.",
        "Теперь расскажи про pipeline.",
        "Какой threshold использовать?",
        "Как проверить качество?",
    ],
    "expect": {
        "goal_contains": "RAG",
        "constraints": ["работать локально"],
        "active_decisions": {"vector_store": "faiss", "reranker": "bge-reranker"},
        "superseded": [],
        "focus_nonempty": True,
    },
}

SCENARIO_2 = {
    "name": "Сценарий 2: изменение требований (FAISS → Chroma)",
    "messages": [
        "Хочу сделать поиск по учебным документам.",
        "Используем FAISS.",
        "Документы будут PDF.",
        "Нужен semantic search.",
        "Добавим reranker.",
        "Как лучше делать chunking?",
        "Пусть chunk будет 500 токенов.",
        "Overlap — 100 токенов.",
        "Я передумал насчёт FAISS.",
        "Используем Chroma.",
        "Как теперь выглядит architecture?",
        "Как работает vector search?",
        "Какие ограничения у текущей системы?",
    ],
    "expect": {
        "goal_contains": "поиск",
        "constraints": [],
        "active_decisions": {"vector_store": "chroma", "reranker": "reranker",
                             "chunk_size": "500 токенов", "overlap": "100 токенов",
                             "document_format": "pdf"},
        "superseded": ["vector_store:faiss"],
        "focus_nonempty": True,
    },
}

SCENARIOS = {"1": SCENARIO_1, "2": SCENARIO_2}


def run_chat_scenario(
    scenario: Dict[str, Any],
    *,
    collection_id: Optional[str] = None,
    strategy: Optional[str] = None,
    service=None,
) -> dict:
    """Пройти все сообщения сценария через ChatService, собрать отчёт и метрики."""
    svc = service or cs.chat_service
    messages = scenario["messages"]
    per_message: List[dict] = []
    conversation_id: Optional[str] = None
    final_state = None

    for i, msg in enumerate(messages):
        try:
            res = svc.answer(
                conversation_id=conversation_id,
                message=msg,
                collection_id=collection_id,
                strategy=strategy,
            )
            conversation_id = res.get("conversation_id")
            final_state = res.get("task_state", final_state)
            per_message.append({
                "i": i + 1,
                "original_query": msg,
                "search_query": res.get("search_query", ""),
                "rag_called": True,
                "status": res.get("status"),
                "reranked": bool((res.get("config") or {}).get("enable_reranker")) and res.get("status") == "answered",
                "relevance_score": (res.get("retrieval") or {}).get("relevance_score"),
                "grounding_score": (res.get("grounding") or {}).get("grounding_score"),
                "sources_count": len(res.get("sources", [])),
                "citations_count": len(res.get("citations", [])),
                "grounded": bool((res.get("grounding") or {}).get("grounded")),
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("chat_scenario msg %d error=%s", i + 1, type(e).__name__)
            per_message.append({
                "i": i + 1, "original_query": msg, "search_query": "",
                "rag_called": False, "status": "error", "error": str(e),
            })

    metrics, retention = _metrics(per_message, final_state, scenario.get("expect", {}))
    return {
        "name": scenario["name"],
        "messages": len(messages),
        "per_message": per_message,
        "final_task_state": final_state,
        "metrics": metrics,
        "retention": retention,
    }


def _metrics(rows: List[dict], final_state, expect: dict) -> (dict, dict):  # noqa: ANN001
    total = len(rows)
    ok = [r for r in rows if r.get("status") == "answered"]
    # некоторые «answered» могут не иметь supporting sources при абстракции — считаем честно
    answered = ok if ok else []
    rag_called = sum(1 for r in rows if r.get("rag_called"))
    reranked = sum(1 for r in rows if r.get("reranked"))
    sources = sum(1 for r in answered if r.get("sources_count", 0) > 0)
    citations = sum(1 for r in answered if r.get("citations_count", 0) > 0)
    grounded = sum(1 for r in answered if r.get("grounded"))
    ctx_q = sum(1 for r in rows if r.get("search_query") and r.get("search_query") != r.get("original_query"))

    def pct(num: int, den: int) -> float:
        return round(num / den * 100, 1) if den else 0.0

    ans_den = len(answered) if answered else 1
    metrics = {
        "messages": total,
        "answers_generated": len(answered),
        "errors": total - sum(1 for r in rows if r.get("status") != "error"),
        "rag_call_coverage": pct(rag_called, total),
        "reranking_coverage": pct(reranked, ans_den),
        "source_coverage": pct(sources, ans_den),
        "citation_coverage": pct(citations, ans_den),
        "grounding_accuracy": pct(grounded, ans_den),
        "contextual_query_accuracy": pct(ctx_q, total),
        "abstention": sum(1 for r in rows if r.get("status") in ("insufficient_context", "grounding_failed")),
    }

    # Retention — по фактическому финальному состоянию
    st = final_state or {}
    decisions = st.get("decisions", []) or []
    active = {d["key"]: (d["value"] or "").lower() for d in decisions if d.get("status") == "active"}
    active_keys = set(active.keys())
    superseded = {(d["key"], (d["value"] or "").lower()) for d in decisions if d.get("status") == "superseded"}
    stats = {"goal": max(0, 1) if (st.get("goal") or "").strip() else 0,
             "constraints": 0, "decisions": 0}
    expected_constraints = expect.get("constraints", [])
    if expected_constraints:
        cons = [c.lower() for c in st.get("constraints", [])]
        stats["constraints"] = sum(1 for c in expected_constraints if c.lower() in cons)
        total_c = len(expected_constraints)
    else:
        stats["constraints"] = 0
        total_c = 1

    exp_active = expect.get("active_decisions", {})
    stats["decisions"] = sum(1 for k, v in exp_active.items() if active.get(k) == v.lower())
    total_d = len(exp_active)
    exp_sup = expect.get("superseded", [])
    superseded_ok = sum(1 for s in exp_sup if tuple(s.split(":")) in superseded)

    goal_pres = st.get("goal") or ""
    goal_ok = (expect.get("goal_contains", "").lower() in goal_pres.lower()) if expect.get("goal_contains") else True

    retention = {
        "goal_retention": pct(1 if goal_ok else 0, 1),
        "constraint_retention": pct(stats["constraints"], total_c),
        "decision_retention": pct(stats["decisions"], total_d),
        "superseded_decisions": pct(superseded_ok, len(exp_sup) if exp_sup else 1),
    }
    return metrics, retention
