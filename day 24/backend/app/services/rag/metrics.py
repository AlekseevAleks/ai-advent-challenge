"""Метрики качества retrieval (Hit@K, Precision@K, Recall@K, MRR).

Вычисляются только по реальному evaluation dataset (ground truth).
Граничные случаи документированы: пустой список релевантных → 0 для всех метрик
(и помечается отдельно), отсутствие предсказаний → 0.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence


def hit_at_k(predicted: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """1.0, если хотя бы один релевантный chunk/источник попал в top-k, иначе 0."""
    if not relevant:
        return 0.0
    return 1.0 if any(pid in set(relevant) for pid in predicted[:k]) else 0.0


def precision_at_k(predicted: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Доля релевантных среди top-k предсказаний.

    Правило: precision = relevant_in_top_k / min(k, len(predicted)).
    Пустой список предсказаний или релевантных → 0 (деления на ноль нет).
    """
    if not relevant or not predicted or k <= 0:
        return 0.0
    rel = set(relevant)
    found = sum(1 for pid in predicted[:k] if pid in rel)
    return found / min(k, len(predicted))


def recall_at_k(predicted: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Доля найденных релевантных (от общего числа релевантных) среди top-k."""
    if not relevant:
        return 0.0
    rel = set(relevant)
    found = sum(1 for pid in predicted[:k] if pid in rel)
    return found / len(rel)


def mrr(predicted: Sequence[str], relevant: Sequence[str], k: int | None = None) -> float:
    """Mean Reciprocal Rank: 1/rank первого релевантного среди top-k (или по всем)."""
    rel = set(relevant)
    if not rel:
        return 0.0
    limit = len(predicted) if k is None else min(k, len(predicted))
    for i, pid in enumerate(predicted[:limit], start=1):
        if pid in rel:
            return 1.0 / i
    return 0.0


def compute_metrics(
    predicted: Sequence[str], relevant: Sequence[str], k: int
) -> dict:
    """Сводка метрик для одного вопроса."""
    return {
        "k": k,
        "hit_at_k": round(hit_at_k(predicted, relevant, k), 4),
        "precision_at_k": round(precision_at_k(predicted, relevant, k), 4),
        "recall_at_k": round(recall_at_k(predicted, relevant, k), 4),
        "mrr": round(mrr(predicted, relevant, k), 4),
        "relevant": len(relevant),
        "predicted": len(predicted),
        "found_relevant": sum(1 for p in predicted[:k] if p in set(relevant)),
    }


def aggregate_metrics(per_question: Iterable[dict], k: int) -> dict:
    """Усреднение метрик по вопросам датасета. Пустой набор → нули + warning."""
    rows = list(per_question)
    n = len(rows)
    if n == 0:
        return {"k": k, "questions": 0, "hit_at_k": 0.0, "precision_at_k": 0.0,
                "recall_at_k": 0.0, "mrr": 0.0, "warning": "no data"}
    return {
        "k": k,
        "questions": n,
        "hit_at_k": round(sum(r["hit_at_k"] for r in rows) / n, 4),
        "precision_at_k": round(sum(r["precision_at_k"] for r in rows) / n, 4),
        "recall_at_k": round(sum(r["recall_at_k"] for r in rows) / n, 4),
        "mrr": round(sum(r["mrr"] for r in rows) / n, 4),
    }


def relevant_keys(item: dict) -> list[str]:
    """Ключи релевантности вопроса в согласованном алфавите:
    chunk_id | "s:<source>" | "sec:<section>".

    Предсказания (predicted) строятся тем же способом:
    [chunk_id, "s:<source>", "sec:<section>"] — см. evaluation_service.
    """
    keys: list[str] = []
    for cid in item.get("relevant_chunk_ids") or []:
        if str(cid).strip():
            keys.append(str(cid))
    for src in item.get("expected_sources") or []:
        if str(src).strip():
            keys.append(f"s:{src.strip()}")
    for sec in item.get("expected_sections") or []:
        if str(sec).strip():
            keys.append(f"sec:{sec.strip()}")
    return list(dict.fromkeys(keys))


def prediction_keys(source: str, section: str | None, chunk_id: str) -> list[str]:
    """Ключи предсказания для одного чанка (тот же алфавит, что relevant_keys)."""
    keys = [str(chunk_id), f"s:{source}"]
    if section:
        keys.append(f"sec:{section}")
    return keys