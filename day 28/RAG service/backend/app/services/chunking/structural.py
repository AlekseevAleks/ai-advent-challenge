"""Structural chunking: разбиение по смысловым границам.

Использует структуру извлечённого текста:
  * заголовки Markdown/RST/DOCX (уровни, путь заголовков);
  * классы и функции исходного кода;
  * страницы PDF;
  * абзацы (fallback, если структуры нет).

Один документ может дать много чанков: большие разделы рекурсивно делятся,
небольшие соседние разделы объединяются (если включено и не нарушает границы).
Содержимое разных файлов никогда не объединяется в один чанк.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ...models.document import Document, TextSegment
from ...schemas.indexing import StructuralParams
from .common import Chunk, pages_for_range


@dataclass
class _Section:
    title: Optional[str]
    kind: str                 # root|section|code_symbol|page
    level: int
    start: int
    end: int
    parent: Optional["_Section"] = None
    children: List["_Section"] = field(default_factory=list)
    symbol_type: Optional[str] = None
    symbol_name: Optional[str] = None

    @property
    def path(self) -> str:
        names: List[str] = []
        cur: Optional[_Section] = self
        while cur is not None and cur.kind != "root":
            if cur.title:
                names.append(cur.title)
            cur = cur.parent
        return " > ".join(reversed(names)) or (self.title or "")


# ---------------------------------------------------------------------------
# Построение дерева разделов
# ---------------------------------------------------------------------------

def _build_outline(
    doc: Document,
    text: str,
    segments: List[TextSegment],
) -> Optional[_Section]:
    """Построить дерево разделов из структурных сегментов. None — структуры нет."""
    boundaries = [s for s in segments if s.kind in ("heading", "code_symbol")]
    if not boundaries:
        pages_only = [s for s in segments if s.kind == "page"]
        if pages_only:
            # PDF без заголовков: страницы становятся разделами
            boundaries = [
                TextSegment(kind="page", title=f"Страница {s.page}", level=1,
                            start=s.start, end=len(text), page=s.page)
                for s in pages_only
            ]
        else:
            return None

    root = _Section(title=doc.title, kind="root", level=0, start=0, end=len(text))
    stack: List[_Section] = [root]

    for seg in sorted(boundaries, key=lambda s: s.start):
        level = seg.level or 1
        # закрыть открытые разделы, у которых уровень >= текущего
        while len(stack) > 1 and stack[-1].level >= level:
            stack.pop()
        parent = stack[-1]
        # закрыть предыдущий открытый раздел
        if stack[-1] is not root and stack[-1].end > seg.start:
            stack[-1].end = seg.start
        section = _Section(
            title=seg.title or seg.extra.get("symbol_name"),
            kind=seg.kind,
            level=level,
            start=seg.start,
            end=len(text),
            parent=parent,
            symbol_type=seg.extra.get("symbol_type"),
            symbol_name=seg.extra.get("symbol_name"),
        )
        parent.children.append(section)
        stack.append(section)

    # закрыть оставшиеся открытыми разделы
    while len(stack) > 1:
        node = stack.pop()
        node.end = len(text)
        if node.parent and node.parent.end > node.end:
            node.parent.end = node.end
    return root


def _own_regions(section: _Section) -> List[Tuple[int, int]]:
    """Диапазоны текста раздела, не покрытые вложенными разделами."""
    cursor = section.start
    regions: List[Tuple[int, int]] = []
    for child in sorted(section.children, key=lambda c: c.start):
        if child.start > cursor:
            regions.append((cursor, child.start))
        cursor = max(cursor, child.end)
    if section.end > cursor:
        regions.append((cursor, section.end))
    return regions


def _nearest_cut(text: str, mid: int, lo: int, hi: int, max_size: int) -> int:
    """Найти границу (пустая строка > перевод строки > конец предложения) около mid."""
    radius = min(max_size // 2, 200)
    a = max(lo, mid - radius)
    b = min(hi, mid + radius)
    for sep in ("\n\n", "\n"):
        idx = text.rfind(sep, a, b)
        if idx != -1:
            return idx + len(sep)
    # конец предложения
    for i in range(b - 1, a, -1):
        if text[i] in ".!?…»":
            return i + 1
    return mid


def _split_range(text: str, start: int, end: int, max_size: int, depth: int = 0) -> List[Tuple[int, int]]:
    """Рекурсивно разделить слишком большой диапазон текста."""
    if end - start <= max_size or depth > 64:
        return [(start, end)] if end > start else []
    mid = (start + end) // 2
    cut = _nearest_cut(text, mid, start, end, max_size)
    if cut <= start or cut >= end or not (start < cut < end):
        cut = start + max_size
        if cut >= end:
            cut = start + (end - start) // 2 + 1
    if cut <= start or cut >= end:
        return [(start, end)]
    left = _split_range(text, start, cut, max_size, depth + 1)
    right = _split_range(text, cut, end, max_size, depth + 1)
    return left + right


# ---------------------------------------------------------------------------
# Fallback: разбиение по абзацам
# ---------------------------------------------------------------------------

def _paragraph_regions(text: str) -> List[Tuple[int, int]]:
    if not text.strip():
        return []
    sep = "\n\n" if "\n\n" in text else "\n"
    regions: List[Tuple[int, int]] = []
    cursor = 0
    for m in __import__("re").finditer(sep, text):
        regions.append((cursor, m.start()))
        cursor = m.end()
    if cursor < len(text):
        regions.append((cursor, len(text)))
    return [r for r in regions if r[1] > r[0]]


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def _make_chunks(
    doc: Document,
    text: str,
    regions: List[Tuple[Optional[_Section], int, int]],
    max_size: int,
) -> List[Tuple[Optional[_Section], int, int]]:
    """Развернуть регионы в чанки, разделяя слишком большие."""
    out: List[Tuple[Optional[_Section], int, int]] = []
    for section, s, e in regions:
        for a, b in _split_range(text, s, e, max_size):
            out.append((section, a, b))
    return out


def _merge_small(
    items: List[Tuple[Optional[_Section], int, int]],
    min_size: int,
    max_size: int,
) -> List[Tuple[Optional[_Section], int, int]]:
    """Объединить небольшие соседние разделы того же документа/родителя."""
    if not items:
        return []
    merged: List[Tuple[Optional[_Section], int, int]] = []
    pending_section, pending_a, pending_b = items[0]
    for section, a, b in items[1:]:
        pending_size = pending_b - pending_a
        cur_size = b - a
        same_parent = (
            (pending_section is None and section is None)
            or (pending_section is not None and section is not None
                and pending_section.parent is section.parent
                and pending_section.parent is not None
                and pending_section.kind == section.kind != "page")
        )
        if same_parent and (pending_size < min_size or cur_size < min_size) \
                and (pending_b - pending_a + cur_size) <= max_size:
            pending_b = b
            if pending_section != section:
                pending_section = pending_section or section
        else:
            merged.append((pending_section, pending_a, pending_b))
            pending_section, pending_a, pending_b = section, a, b
    merged.append((pending_section, pending_a, pending_b))
    return merged


def chunk_structural(
    doc: Document,
    text: str,
    params: StructuralParams,
    segments: Optional[List[TextSegment]] = None,
) -> List[Chunk]:
    if segments is None:
        segments = getattr(doc, "_segments", []) or []
    root = _build_outline(doc, text, segments)

    if root is None:
        # Fallback: абзацы, затем деление слишком больших
        regions = _paragraph_regions(text)
        items: List[Tuple[Optional[_Section], int, int]] = [
            (None, s, e) for s, e in regions
        ]
        items = _make_chunks(doc, text, items, params.max_chunk_size)
        items = _merge_small(items, params.min_chunk_size, params.max_chunk_size)
    else:
        # DFS: регионы каждой секции, не покрытые детьми
        raw: List[Tuple[Optional[_Section], int, int]] = []
        stack = [root]
        while stack:
            node = stack.pop()
            for s, e in _own_regions(node):
                if e > s:
                    raw.append((node, s, e))
            stack.extend(node.children)
        raw.sort(key=lambda r: (r[1], r[2]))
        items = _make_chunks(doc, text, raw, params.max_chunk_size)
        items = _merge_small(items, params.min_chunk_size, params.max_chunk_size)

    pages = getattr(doc, "_pages", []) or []
    chunks: List[Chunk] = []
    for idx, (section, s, e) in enumerate(items):
        start = max(0, s)
        end = min(len(text), e)
        if end <= start:
            continue
        t = text[start:end]
        if not t.strip():
            continue
        p_in, p_out = pages_for_range(pages, start, end)
        symbol_type = section.symbol_type if section else None
        symbol_name = section.symbol_name if section else None
        section_path = section.path if section and section.path else None
        chunks.append(Chunk(
            document_id=doc.id,
            source=doc.source,
            title=doc.title,
            section=section_path,
            text=t,
            chunk_index=idx,
            chunking_strategy="structural",
            start_offset=start,
            end_offset=end,
            page_start=p_in,
            page_end=p_out,
            symbol_type=symbol_type,
            symbol_name=symbol_name,
        ))
    return chunks