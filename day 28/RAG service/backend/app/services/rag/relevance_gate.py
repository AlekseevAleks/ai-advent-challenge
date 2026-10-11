"""Relevance Gate: первый обязательный отсев перед вызовом generative-модели.

Использует лучший доступный сигнал релевантности найденных чанков:
* reranker_score — если реранкинг включён;
* иначе retrieval_score (max similarity).

Если релевантность ниже порога ИЛИ найдено слишком мало подтверждающих
чанков — generative-модель НЕ вызывается, возвращается «не знаю».
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


def chunk_relevance_score(chunk: Dict) -> float:
    """Наилучший сигнал релевантности отдельного чанка."""
    r = chunk.get("reranker_score")
    if r is not None:
        return float(r)
    return float(chunk.get("retrieval_score", 0.0))


@dataclass
class RelevanceVerdict:
    relevance_score: float
    threshold: float
    min_supporting_chunks: int
    enough_chunks: bool
    passed: bool


def evaluate(
    chunks: List[Dict],
    threshold: float,
    min_supporting_chunks: int = 1,
) -> RelevanceVerdict:
    """Проверка relevance gate.

    Правило сравнения: чанк считается релевантным, если
    `relevance_score >= threshold`. Блок проходит gate, если найдено хотя бы
    `min_supporting_chunks` релевантных чанков.
    """
    if not chunks:
        return RelevanceVerdict(0.0, threshold, min_supporting_chunks, False, False)
    score = max(chunk_relevance_score(c) for c in chunks)
    relevant = [c for c in chunks if chunk_relevance_score(c) >= threshold]
    enough = len(chunks) >= min_supporting_chunks and len(relevant) >= min_supporting_chunks
    passed = enough and score >= threshold
    return RelevanceVerdict(score, threshold, min_supporting_chunks, enough, passed)
