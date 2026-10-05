"""Fixed-size chunking: разрезание текста на чанки фиксированного размера
с перекрытием (overlap) и аккуратным выбором границ (предложения/слова)."""

from __future__ import annotations

import re
from typing import List, Optional

from ...models.document import Document
from ...schemas.indexing import FixedSizeParams
from .common import Chunk, pages_for_range


def _find_boundary(text: str, start: int, raw_end: int, keep_min: int) -> int:
    """Найти границу внутри [start, raw_end): конец предложения > граница слова > жёсткий срез."""
    window = text[start:raw_end]
    if len(window) <= keep_min:
        return raw_end
    for i in range(len(window) - 1, keep_min - 1, -1):
        ch = window[i]
        if ch in ".!?…»":
            # не отрезать внутри сокращений вида «т.д.» или чисел «3.5»
            if ch == ".":
                nxt = window[i + 1] if i + 1 < len(window) else " "
                prev = window[i - 1] if i > 0 else " "
                if prev.isdigit() and nxt.isdigit():
                    continue
                if nxt.isalpha() and nxt.islower():
                    continue
                if nxt == "." or (i + 1 < len(window) and window[i + 1] == " " and
                                  i + 2 < len(window) and window[i + 2] == "."):
                    continue
            return start + i + 1
        if ch == "\n" and i + 1 < len(window) and window[i + 1] == "\n":
            return start + i + 1
    for i in range(len(window) - 1, keep_min - 1, -1):
        if window[i].isspace():
            return start + i + 1
    return raw_end


def _chunk_by_chars(text: str, size: int, overlap: int) -> List[tuple[int, int]]:
    if not text.strip():
        return []
    spans: List[tuple[int, int]] = []
    n = len(text)
    start = 0
    keep_min = max(1, overlap)
    while start < n:
        raw_end = min(n, start + size)
        # короткий «хвостик» присоединяем к предыдущему чанку, если не превышает размер
        if raw_end == n and (n - start) <= keep_min and spans:
            prev_start, prev_end = spans[-1]
            if n - prev_start <= size:
                spans[-1] = (prev_start, n)
                break
        end = _find_boundary(text, start, raw_end, keep_min)
        if end <= start:
            end = min(n, start + size)
        spans.append((start, end))
        if end >= n:
            break
        start = max(overlap, end - overlap) if end - overlap > start else end
    return spans


def _token_positions(text: str) -> Optional[List[int]]:
    """Границы токенов через tiktoken (если установлен). None — если недоступен."""
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001
        return None
    pos: List[int] = []
    for m in re.finditer(r"\S+", text):
        word = m.group(0)
        toks = enc.encode(word)
        if len(toks) == 1:
            pos.append(m.end())
        else:
            seg_len = max(1, len(word))
            for j in range(len(toks)):
                pos.append(m.start() + min(seg_len - 1, (j + 1) * seg_len // len(toks)))
    pos.sort()
    return pos


def _chunk_by_tokens(text: str, size: int, overlap: int, positions: List[int]) -> List[tuple[int, int]]:
    n_tokens = len(positions)
    if n_tokens == 0:
        return _chunk_by_chars(text, size * 4, overlap * 4)
    spans: List[tuple[int, int]] = []
    start_tok = 0
    while start_tok < n_tokens:
        end_tok = min(n_tokens, start_tok + size)
        start_char = 0 if start_tok == 0 else positions[start_tok - 1]
        end_char = positions[end_tok - 1]
        spans.append((start_char, end_char))
        if end_tok >= n_tokens:
            break
        next_start = end_tok - overlap
        if next_start <= start_tok:
            next_start = start_tok + 1
        start_tok = next_start
    return spans


def chunk_fixed_size(
    doc: Document,
    text: str,
    params: FixedSizeParams,
) -> List[Chunk]:
    """Разбить текст фиксированными чанками с перекрытием.

    Единица измерения: символы (по умолчанию) или токены (требуется tiktoken).
    """
    if params.unit == "tokens":
        positions = _token_positions(text)
        if positions is None:
            raise ValueError(
                "Подсчёт токенов недоступен: не установлен пакет tiktoken. "
                "Установите его (`pip install tiktoken`) или используйте единицу «символы»."
            )
        spans = _chunk_by_tokens(text, params.chunk_size, params.overlap, positions)
    else:
        spans = _chunk_by_chars(text, params.chunk_size, params.overlap)

    chunks: List[Chunk] = []
    for idx, (s, e) in enumerate(spans):
        start = max(0, s)
        end = min(len(text), e)
        if end <= start:
            continue
        t = text[start:end]
        if not t.strip():
            continue
        pages = getattr(doc, "_pages", []) or []
        p_in, p_out = pages_for_range(pages, start, end)
        chunks.append(Chunk(
            document_id=doc.id,
            source=doc.source,
            title=doc.title,
            section=None,
            text=t,
            chunk_index=idx,
            chunking_strategy="fixed_size",
            start_offset=start,
            end_offset=end,
            page_start=p_in,
            page_end=p_out,
        ))
    return chunks