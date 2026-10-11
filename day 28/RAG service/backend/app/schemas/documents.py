"""Схемы документов."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    id: str
    source: str                              # оригинальное имя файла
    title: str                              # отображаемый заголовок
    file_type: str
    file_size: int
    storage_name: str
    char_count: Optional[int] = None
    page_count: Optional[int] = None
    status: str                             # uploaded|extracting|ready|indexing|indexed|error
    content_hash: str
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    created_at: str
    extracted_at: Optional[str] = None
    has_text: bool = False


class UploadErrorItem(BaseModel):
    filename: str
    message: str


class UploadResponse(BaseModel):
    documents: List[DocumentOut] = Field(default_factory=list)
    errors: List[UploadErrorItem] = Field(default_factory=list)
    uploaded: int = 0
    failed: int = 0


class DocumentTextOut(BaseModel):
    id: str
    source: str
    text: str
    char_count: int
    page_count: Optional[int] = None
    warnings: List[str] = Field(default_factory=list)
    truncated: bool = False


class ExtractResponse(BaseModel):
    document: DocumentOut
    char_count: int
    page_count: Optional[int] = None
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)