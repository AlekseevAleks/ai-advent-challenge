"""Доменные модели (слой между репозиториями и сервисами)."""

from .document import Document, ExtractionResult, TextSegment  # noqa: F401
from .collection import Collection, IndexRecord  # noqa: F401

__all__ = ["Document", "ExtractionResult", "TextSegment", "Collection", "IndexRecord"]