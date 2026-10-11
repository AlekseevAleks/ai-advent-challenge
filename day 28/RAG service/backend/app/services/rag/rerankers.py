"""Реранкеры: pluggable второй этап ранжирования.

Интерфейс `BaseReranker.rerank(query, documents) -> list[float]`.

Реализации:
  * SimilarityReranker  — контрольный: оценка близка retrieval similarity
    (нормированная min-max по кандидатам). Это НЕ настоящий cross-encoder,
    а учебная точка отсчёта.
  * HeuristicReranker   — 0.7*semantic + 0.2*keyword + 0.1*metadata.
  * CrossEncoderReranker — локальная cross-encoder модель (sentence-transformers,
    напр. BAAI/bge-reranker-base). Ленивая загрузка; если модель/библиотека
    недоступны — RerankerUnavailable с понятным советом.
"""

from __future__ import annotations

import math
import re
import threading
from abc import ABC, abstractmethod
from typing import List, Optional

from ...utils.logging import get_logger

logger = get_logger(__name__)

RERANKER_KINDS = ("heuristic", "cross_encoder", "similarity")

# Значимые слова запроса (стоп-слова исключаются)
_STOPWORDS = set("""a an the is are was were be been am this that these those it its he she they
we you i me my your our of to in on at for with from by as and or but not no so if then
what which who whom whose when where why how do does did done doing have has had having
can could will would shall should may might must about into over under above below again
если есть это того что как по не ни да нет они она он мы вы я мой твой наш ваш их его её
из на при в с к о от до за под над про и но а или у же бы ли чтобы потому поэтому также
который которая которое которые какому какой какая каким какие чем чему где когда""".split())

_TOKEN_RE = re.compile(r"[а-яёa-z0-9_\-]+", re.IGNORECASE)


class RerankerUnavailable(Exception):
    """Реранкер недоступен: не установлена библиотека или не скачана модель."""

    def __init__(self, message: str, install_hint: Optional[str] = None):
        super().__init__(message)
        self.install_hint = install_hint


class BaseReranker(ABC):
    """Интерфейс реранкера: query + кандидаты -> оценки релевантности."""

    kind: str = "base"
    model: Optional[str] = None

    @abstractmethod
    def rerank(self, query: str, documents: List[str]) -> List[float]:
        """Вернуть список оценок в том же порядке, что и documents."""

    def availability(self) -> dict:
        return {"available": True, "reason": None, "install_hint": None}


# ---------------------------------------------------------------------------
# Контрольный reranker на основе retrieval similarity
# ---------------------------------------------------------------------------

class SimilarityReranker(BaseReranker):
    """Контрольный реранкер: использует retrieval similarity (min-max норма).

    Не добавляет нового сигнала — служит для сравнения интерфейсов.
    """

    kind = "similarity"

    def __init__(self, base_scores: Optional[List[float]] = None):
        self._base = base_scores

    def rerank(self, query: str, documents: List[str]) -> List[float]:
        scores = self._base if self._base is not None else [0.0] * len(documents)
        if not scores:
            return []
        lo, hi = min(scores), max(scores)
        norm = hi - lo or 1.0
        return [round((s - lo) / norm, 6) for s in scores]


# ---------------------------------------------------------------------------
# Heuristic-реранкер (учебный)
# ---------------------------------------------------------------------------

class HeuristicReranker(BaseReranker):
    """final = 0.7*semantic + 0.2*keyword + 0.1*metadata.

    semantic — retrieval similarity (cosine), обрезанная до [0..1];
    keyword — доля значимых слов query, встреченных в тексте чанка;
    metadata — доля значимых слов query в первой строке чанка (заголовок/section).
    """

    kind = "heuristic"

    def __init__(self, base_scores: Optional[List[float]] = None):
        self._base = base_scores

    @staticmethod
    def _significant_tokens(query: str) -> List[str]:
        return [
            w.lower() for w in _TOKEN_RE.findall(query)
            if len(w) > 1 and w.lower() not in _STOPWORDS
        ]

    @staticmethod
    def _keyword_score(tokens: List[str], text: str) -> float:
        if not tokens:
            return 0.0
        low = text.lower()
        hits = sum(1 for t in tokens if t in low)
        return hits / len(tokens)

    def rerank(self, query: str, documents: List[str]) -> List[float]:
        base = self._base if self._base is not None else [0.0] * len(documents)
        tokens = self._significant_tokens(query)
        out = []
        for doc in documents:
            semantic = max(0.0, base[len(out)]) if base else 0.0  # сырая similarity, обрезанная до [0..1]
            keyword = self._keyword_score(tokens, doc)
            meta_signal = self._keyword_score(tokens, doc.splitlines()[0]) if doc.splitlines() else 0.0
            score = 0.7 * semantic + 0.2 * keyword + 0.1 * meta_signal
            out.append(round(float(score), 6))
        return out


# ---------------------------------------------------------------------------
# Cross-encoder (локальный)
# ---------------------------------------------------------------------------

class CrossEncoderReranker(BaseReranker):
    """Локальная cross-encoder модель (sentence-transformers, напр. BAAI/bge-reranker-base).

    Модель и библиотека загружаются лениво и кэшируются в процессе.
    """

    kind = "cross_encoder"

    def __init__(self, model: str = "BAAI/bge-reranker-base"):
        self.model = model or "BAAI/bge-reranker-base"
        self._model_obj = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model_obj is not None:
            return self._model_obj
        with self._lock:
            if self._model_obj is not None:
                return self._model_obj
            try:
                from sentence_transformers import CrossEncoder
            except ImportError:
                raise RerankerUnavailable(
                    "Cross-encoder недоступен: не установлена библиотека sentence-transformers.",
                    install_hint="pip install sentence-transformers",
                )
            try:
                self._model_obj = CrossEncoder(self.model)
            except Exception as e:  # noqa: BLE001
                raise RerankerUnavailable(
                    f"Не удалось загрузить модель переранжирования «{self.model}»: {e}",
                    install_hint=f"huggingface-cli download {self.model} (или установите sentence-transformers)",
                )
        return self._model_obj

    def rerank(self, query: str, documents: List[str]) -> List[float]:
        if not documents:
            return []
        model = self._load()
        pairs = [(query, doc[:1200]) for doc in documents]  # ограничение токенов
        scores = model.predict(pairs, show_progress_bar=False, batch_size=32)
        return [round(float(max(0.0, s)), 6) for s in scores]

    def availability(self) -> dict:
        try:
            self._load()
            return {"available": True, "reason": None, "install_hint": None}
        except RerankerUnavailable as e:
            return {"available": False, "reason": str(e), "install_hint": e.install_hint}


# ---------------------------------------------------------------------------
# Фабрика
# ---------------------------------------------------------------------------

def build_reranker(
    kind: str,
    model: Optional[str] = None,
    base_scores: Optional[List[float]] = None,
) -> BaseReranker:
    if kind == "heuristic":
        return HeuristicReranker(base_scores=base_scores)
    if kind == "similarity":
        return SimilarityReranker(base_scores=base_scores)
    if kind == "cross_encoder":
        return CrossEncoderReranker(model=model or "BAAI/bge-reranker-base")
    raise ValueError(f"Неизвестный тип реранкера: {kind!r}")


def rerankers_status(default_model: str) -> dict:
    """Статусы всех известных реранкеров (без загрузки больших моделей)."""
    out = {}
    for kind in RERANKER_KINDS:
        try:
            r = build_reranker(kind, model=default_model)
            st = r.availability()
            out[kind] = {"reranker": kind, "model": r.model or default_model, **st}
        except Exception as e:  # noqa: BLE001
            out[kind] = {"reranker": kind, "model": default_model,
                         "available": False, "reason": str(e), "install_hint": None}
    return out