"""Модель документа."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class TextSegment:
    """Структурный сегмент исходного текста (заголовок, символ кода, страница, абзац)."""

    kind: str                # heading | code_symbol | page | paragraph
    title: Optional[str] = None
    level: Optional[int] = None
    start: int = 0           # символьное смещение в text
    end: int = 0
    page: Optional[int] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    text: str
    char_count: int = 0
    page_count: Optional[int] = None
    pages: List[dict[str, Any]] = field(default_factory=list)   # [{page, start, end}]
    segments: List[TextSegment] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    encoding: Optional[str] = None


@dataclass
class Document:
    id: str
    original_name: str
    storage_name: str
    file_type: str
    file_size: int
    path: str
    content_hash: str
    status: str = "uploaded"
    extracted_path: Optional[str] = None
    char_count: Optional[int] = None
    page_count: Optional[int] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    created_at: str = ""
    extracted_at: Optional[str] = None
    indexed_at: Optional[str] = None

    @property
    def title(self) -> str:
        return self.original_name

    @property
    def source(self) -> str:
        return self.original_name

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Document":
        if row is None:
            raise ValueError("document not found")
        return cls(
            id=row["id"],
            original_name=row["original_name"],
            storage_name=row["storage_name"],
            file_type=row["file_type"],
            file_size=row["file_size"],
            path=row["path"],
            content_hash=row["content_hash"],
            status=row["status"],
            extracted_path=row.get("extracted_path"),
            char_count=row.get("char_count"),
            page_count=row.get("page_count"),
            warnings=json.loads(row.get("warnings") or "[]"),
            errors=json.loads(row.get("errors") or "[]"),
            created_at=row.get("created_at") or "",
            extracted_at=row.get("extracted_at"),
            indexed_at=row.get("indexed_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "original_name": self.original_name,
            "storage_name": self.storage_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "path": self.path,
            "content_hash": self.content_hash,
            "status": self.status,
            "extracted_path": self.extracted_path,
            "char_count": self.char_count,
            "page_count": self.page_count,
            "warnings": self.warnings,
            "errors": self.errors,
            "created_at": self.created_at,
            "extracted_at": self.extracted_at,
            "indexed_at": self.indexed_at,
        }