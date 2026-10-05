"""Citation Builder: формирование и проверка цитат из реальных чанков.

Цитата — это реальный фрагмент найденного chunk. Backend НЕ доверяет модели:
quote извлекается непосредственно из текста чанка по chunk_id, а не из
сгенерированного моделью текста.
"""

from __future__ import annotations

import re
from typing import Dict, List

from ...schemas.rag import AnswerCitation, AnswerSource


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_quote(text: str, max_chars: int = 240) -> str:
    """Взять реальный фрагмент текста чанка (гарантированный подстрока).

    Обрезает по границе предложения, затем — слова, никогда не выходя за
    max_chars и не изобретая текст.
    """
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # граница предложения (последняя точка/вопросительный/восклицательный до среза)
    for i in range(len(cut) - 1, 0, -1):
        if cut[i] in ".!?…" :
            return (cut[: i + 1]).strip()
    # граница слова
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.strip()


def validate_quote(quote: str, chunk_text: str) -> bool:
    """Проверка, что цитата действительно присутствует в chunk.

    Правило: нормализованная цитата должна быть ПОЛНОЙ подстрокой
    нормализованного текста чанка (устойчиво к переносам строк/пробелам).
    """
    if not quote:
        return False
    q = _normalize(quote)
    c = _normalize(chunk_text)
    return bool(q) and q in c


def build_source(chunk: Dict) -> AnswerSource:
    return AnswerSource(
        source=chunk.get("source", ""),
        section=chunk.get("section"),
        chunk_id=chunk.get("chunk_id", ""),
        title=chunk.get("title"),
        page_start=chunk.get("page_start"),
        page_end=chunk.get("page_end"),
        symbol_name=chunk.get("symbol_name"),
    )


def build_citations(
    chunks: Dict[str, Dict],
    referenced_chunk_ids: List[str],
    max_quote_chars: int = 240,
) -> List[AnswerCitation]:
    """Построить цитаты для чанков, на которые ссылаются claims.

    Пропускаются отсутствующие chunk_id; quote всегда — реальный фрагмент
    текста чанка (валидируется `validate_quote`).
    """
    out: List[AnswerCitation] = []
    seen = set()
    for cid in referenced_chunk_ids:
        if not cid or cid in seen:
            continue
        chunk = chunks.get(cid)
        if chunk is None:
            continue
        quote = extract_quote(chunk.get("text", ""), max_quote_chars)
        if not quote:
            continue
        out.append(
            AnswerCitation(
                source=chunk.get("source", ""),
                section=chunk.get("section"),
                chunk_id=cid,
                quote=quote,
                page_start=chunk.get("page_start"),
                page_end=chunk.get("page_end"),
            )
        )
        seen.add(cid)
    return out
