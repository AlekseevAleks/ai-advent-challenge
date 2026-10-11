"""Общие структуры chunking: чанк и его метаданные."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...utils.ids import make_chunk_id


@dataclass
class Chunk:
    document_id: str
    source: str
    title: str
    section: Optional[str]
    text: str
    chunk_index: int
    chunking_strategy: str
    start_offset: int
    end_offset: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    symbol_type: Optional[str] = None
    symbol_name: Optional[str] = None
    chunk_id: str = field(default_factory=make_chunk_id)

    @property
    def char_count(self) -> int:
        return len(self.text)

    def to_metadata(self, collection_id: str, model: str, index_version: int) -> dict[str, Any]:
        """Метаданные чанка (схема метаданных v1).

        Позиция записи в этом списке однозначно соответствует позиции вектора в FAISS.
        """
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "source": self.source,
            "title": self.title,
            "section": self.section,
            "text": self.text,
            "chunk_index": self.chunk_index,
            "chunking_strategy": self.chunking_strategy,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "char_count": self.char_count,
            "embedding_model": model,
            "collection_id": collection_id,
            "index_version": index_version,
            "symbol_type": self.symbol_type,
            "symbol_name": self.symbol_name,
        }


CHUNK_STRATEGIES = ("fixed_size", "structural")
METADATA_SCHEMA_VERSION = 1


def pages_for_range(pages: List[dict[str, Any]], start: int, end: int) -> tuple[Optional[int], Optional[int]]:
    """Номера страниц, пересекающих диапазон [start, end)."""
    if not pages:
        return None, None
    lo, hi = None, None
    for p in pages:
        p_start, p_end = p.get("start", 0), p.get("end", 0)
        if p_end > start and p_start < end:
            if lo is None:
                lo = p.get("page")
            hi = p.get("page")
    return lo, hi