"""Эндпоинты документов."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, File, Query, UploadFile

from ..models.document import Document
from ..schemas.documents import (
    DocumentOut,
    DocumentTextOut,
    ExtractResponse,
    UploadResponse,
)
from ..services.demo_corpus import load_demo_documents
from ..services.document_loader import loader
from ..utils.errors import NotFoundError

router = APIRouter(prefix="/api/documents", tags=["Документы"])


def _out(doc: Document) -> DocumentOut:
    return loader.to_out(doc)


@router.post("/upload", summary="Загрузка файлов", response_model=UploadResponse)
async def upload_documents(files: List[UploadFile] = File(...)) -> UploadResponse:
    """Загрузка нескольких файлов (multipart). Возвращает загруженные документы и ошибки."""
    return await loader.upload(files)


@router.post("/demo", summary="Загрузить демонстрационные документы", response_model=UploadResponse)
def upload_demo() -> UploadResponse:
    return load_demo_documents()


@router.get("", summary="Список документов", response_model=List[DocumentOut])
def list_documents() -> List[DocumentOut]:
    return [_out(d) for d in loader.get_all()]


@router.get("/{document_id}", summary="Информация о документе", response_model=DocumentOut)
def get_document(document_id: str) -> DocumentOut:
    return _out(loader.get_required(document_id))


@router.get("/{document_id}/text", summary="Извлечённый текст документа", response_model=DocumentTextOut)
def get_document_text(document_id: str, preview: int = Query(default=0, ge=0)) -> DocumentTextOut:
    doc = loader.get_required(document_id)
    res = loader.load_text(doc)
    text = res.text
    if doc.status == "error" and not text:
        raise NotFoundError(
            "Не удалось извлечь текст из документа." + (" Возможно, PDF содержит сканы." if doc.file_type == "PDF" else ""),
            code="extraction_failed",
        )
    truncated = False
    if preview and len(text) > preview:
        text = text[:preview]
        truncated = True
    return DocumentTextOut(
        id=doc.id,
        source=doc.source,
        text=text,
        char_count=res.char_count,
        page_count=res.page_count,
        warnings=res.warnings,
        truncated=truncated,
    )


@router.post("/{document_id}/extract", summary="Повторное извлечение текста", response_model=ExtractResponse)
def extract_document(document_id: str) -> ExtractResponse:
    doc = loader.reextract(document_id)
    return ExtractResponse(
        document=_out(doc),
        char_count=doc.char_count or 0,
        page_count=doc.page_count,
        warnings=doc.warnings,
        errors=doc.errors,
    )


@router.delete("/{document_id}", summary="Удалить документ", status_code=204)
def delete_document(document_id: str) -> None:
    if not loader.delete(document_id):
        raise NotFoundError("Документ не найден", code="document_not_found")