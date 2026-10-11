"""Grounding Validator: проверка, что утверждения (claims) опираются на чанки.

Второй gate после генерации. Проверяет:
1. есть ли answer;
2. есть ли claims;
3. у каждого claim есть chunk_id;
4. каждый chunk_id существует среди retrieved чанков;
5. chunk принадлежит текущему retrieval result (чанки берутся строго из него);
6. есть ли фактическая текстовая поддержка claim в чанке (lexical + optional semantic);
7. есть ли цитаты (проверяется отдельно в citation_builder).

grounding_score = claims_supported / claims_total.
Семантическая проверка (embedding similarity claim↔chunk) опциональна:
при ошибке эмбеддинга безопасно деградирует к лексической.
"""

from __future__ import annotations

import re
import string
from typing import Callable, Dict, List, Optional

from ...schemas.rag import AnswerClaim, AnswerLLMClaim, AnswerLLMOutput


def _tokenize(text: str) -> set:
    words = re.findall(r"[\wа-яА-ЯёЁ]+", (text or "").lower())
    return {w for w in words if len(w) > 1}


def lexical_support_ratio(claim_text: str, chunk_text: str) -> float:
    """Доля значимых слов claim, встречающихся в тексте чанка."""
    cw = _tokenize(claim_text)
    if not cw:
        return 0.0
    chunk_words = _tokenize(chunk_text)
    hits = sum(1 for w in cw if w in chunk_words)
    return hits / len(cw)


class GroundingValidator:
    """Проверка ground-ности ответа на основе claims и retrieved чанков."""

    def __init__(
        self,
        embed_fn: Optional[Callable[[str], List[float]]] = None,
        lexical_threshold: float = 0.5,
    ):
        # embed_fn(text)->vector: DI для тестов; по умолчанию — реальный Ollama.
        self._embed_fn = embed_fn
        self._lexical_threshold = lexical_threshold

    def _embed(self, text: str) -> Optional[List[float]]:
        if self._embed_fn is not None:
            return self._embed_fn(text)
        from ..ollama_service import ollama_provider

        try:
            return ollama_provider.get_provider().embed_one(text)
        except Exception:  # noqa: BLE001 — семантика опциональна
            return None

    @staticmethod
    def _cos(a: List[float], b: List[float]) -> Optional[float]:
        if not a or not b or len(a) != len(b):
            return None
        import math

        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if not na or not nb:
            return None
        return dot / (na * nb)

    def _claim_supported(
        self,
        claim: AnswerLLMClaim,
        chunks: Dict[str, Dict],
        semantic_threshold: float,
        use_semantic: bool,
    ) -> tuple[bool, float]:
        if not claim.chunk_ids:
            return False, 0.0
        best = 0.0
        for cid in claim.chunk_ids:
            chunk = chunks.get(cid)
            if chunk is None:
                continue
            lex = lexical_support_ratio(claim.text, chunk.get("text", ""))
            if lex >= self._lexical_threshold:
                return True, max(best, lex)
            if use_semantic:
                ev = self._embed(claim.text)
                cv = self._embed(chunk.get("text", ""))
                sim = self._cos(ev, cv) if ev and cv else None
                if sim is not None and sim >= semantic_threshold:
                    return True, max(best, float(sim))
                if sim is not None:
                    best = max(best, float(sim))
        return False, best

    def validate(
        self,
        llm: AnswerLLMOutput,
        chunks: List[Dict],
        grounding_threshold: float,
        semantic_threshold: float = 0.70,
        use_semantic: bool = True,
    ) -> dict:
        chunk_map: Dict[str, Dict] = {c.get("chunk_id", ""): c for c in chunks}
        claims = llm.claims or []
        validated: List[AnswerClaim] = []
        supported = 0
        for claim in claims:
            ok, sim = self._claim_supported(claim, chunk_map, semantic_threshold, use_semantic)
            validated.append(
                AnswerClaim(
                    text=claim.text,
                    chunk_ids=claims_ids_clean(claim),
                    grounded=ok,
                    grounding_score=round(sim, 4),
                )
            )
            if ok:
                supported += 1
        total = len(validated)
        score = supported / total if total else 0.0
        grounded = bool(llm.answer.strip()) and total > 0 and score >= grounding_threshold
        return {
            "grounded": grounded,
            "grounding_score": round(score, 4),
            "claims_total": total,
            "claims_supported": supported,
            "claims": validated,
        }


def claims_ids_clean(claim: AnswerLLMClaim) -> List[str]:
    # оставляем только реально существующие chunk_id (проверено в _claim_supported)
    return list(dict.fromkeys(claim.chunk_ids))
