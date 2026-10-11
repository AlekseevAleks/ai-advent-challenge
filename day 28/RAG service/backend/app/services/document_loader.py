"""Загрузка документов: валидация, сохранение, извлечение текста, кэш текста.

Каждый документ — единый объект с полями document_id, source, title, file_type,
text, page_count, file_size, created_at, content_hash. Извлечённый текст
кэшируется в JSON-файл рядом с оригиналом (storage/uploads/<doc_id>/extracted.json).
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import UploadFile

from ..models.document import Document, ExtractionResult, TextSegment
from ..repositories import documents_repo
from ..schemas.documents import DocumentOut, UploadErrorItem, UploadResponse
from ..utils.common import sha256_bytes, utc_now_iso
from ..utils.errors import NotFoundError, ValidationError2
from ..utils.files import safe_filename, unique_storage_filename
from ..utils.ids import new_id
from ..utils.logging import get_logger
from . import runtime
from .text_extractor import extract_text

logger = get_logger(__name__)

MAX_READ_CHUNK = 1 << 20  # 1 МБ


class DocumentLoader:
    """Сервис загрузки и извлечения документов."""

    def __init__(self) -> None:
        self._mutex = threading.Lock()

    # ------------------------------------------------------------------
    # Загрузка файлов (multipart / байты)
    # ------------------------------------------------------------------
    async def upload(
        self, files: List[UploadFile], existing_names: Optional[Set[str]] = None
    ) -> UploadResponse:
        settings = runtime.effective_settings()
        max_files = settings.max_files_per_request
        max_bytes = settings.max_file_size_mb * 1024 * 1024
        if len(files) > max_files:
            raise ValidationError2(
                f"За один запрос можно загрузить не более {max_files} файлов",
                code="too_many_files",
            )
        if existing_names is None:
            existing_names = {d["storage_name"] for d in documents_repo.list_documents()}

        response = UploadResponse()
        for f in files:
            try:
                original = safe_filename(f.filename or "file")
                data = await self._read_limited(f, max_bytes)
                doc = self.add_bytes(original, data, existing_names)
                existing_names.add(doc.storage_name)
                response.documents.append(self.to_out(doc))
                response.uploaded += 1
            except (ValidationError2, ValueError) as e:
                response.errors.append(
                    UploadErrorItem(filename=f.filename or "?", message=str(e))
                )
                response.failed += 1
        return response

    @staticmethod
    async def _read_limited(f: UploadFile, max_bytes: int) -> bytes:
        data = b""
        while True:
            chunk = await f.read(MAX_READ_CHUNK)
            if not chunk:
                break
            data += chunk
            if len(data) > max_bytes:
                raise ValidationError2(
                    f"Файл «{safe_filename(f.filename or 'file')}» больше лимита "
                    f"{max_bytes // (1024 * 1024)} МБ",
                    code="file_too_large",
                )
        if not data:
            raise ValidationError2(
                f"Файл «{safe_filename(f.filename or 'file')}» пуст", code="empty_file"
            )
        return data

    def add_bytes(
        self, original: str, data: bytes, existing_names: Optional[Set[str]] = None
    ) -> Document:
        """Сохранить документ по байтам (используется загрузкой, demo и тестами)."""
        settings = runtime.effective_settings()
        allowed = set(settings.allowed_extension_list)
        original = safe_filename(original)
        ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
        if ext not in allowed:
            raise ValidationError2(
                f"Неподдерживаемый формат «.{ext}» для файла «{original}». "
                f"Разрешены: {', '.join(sorted(allowed))}",
                code="unsupported_format",
            )
        max_bytes = settings.max_file_size_mb * 1024 * 1024
        if len(data) > max_bytes:
            raise ValidationError2(
                f"Файл «{original}» больше лимита {settings.max_file_size_mb} МБ",
                code="file_too_large",
            )
        if not data:
            raise ValidationError2(f"Файл «{original}» пуст", code="empty_file")
        doc_id = new_id("doc")
        paths = runtime.ensure_dirs()
        upload_dir = paths.upload_dir(doc_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        if existing_names is None:
            existing_names = {d["storage_name"] for d in documents_repo.list_documents()}
        storage_name = unique_storage_filename(original, existing_names)
        target = upload_dir / storage_name
        target.write_bytes(data)

        record: Dict[str, Any] = {
            "id": doc_id,
            "original_name": original,
            "storage_name": storage_name,
            "file_type": ext,
            "file_size": len(data),
            "path": str(target),
            "content_hash": sha256_bytes(data),
            "status": "extracting",
            "warnings": [],
            "errors": [],
        }
        documents_repo.create_document(record)
        doc = Document.from_row(documents_repo.get_document(doc_id))
        self._extract_and_store(doc)
        return self.get(doc_id)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Извлечение и кэш
    # ------------------------------------------------------------------
    def extraction_path(self, doc_id: str) -> Path:
        return runtime.get_paths().upload_dir(doc_id) / "extracted.json"

    def _save_extraction(self, doc_id: str, res: ExtractionResult) -> Path:
        path = self.extraction_path(doc_id)
        payload = {
            "text": res.text,
            "char_count": res.char_count,
            "page_count": res.page_count,
            "pages": res.pages,
            "segments": [
                {
                    "kind": s.kind, "title": s.title, "level": s.level,
                    "start": s.start, "end": s.end, "page": s.page,
                    "extra": s.extra,
                }
                for s in res.segments
            ],
            "warnings": res.warnings,
            "errors": res.errors,
            "encoding": res.encoding,
            "extracted_at": utc_now_iso(),
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def _extract_and_store(self, doc: Document) -> Document:
        with self._mutex:
            file_path = Path(doc.path)
            if not file_path.exists():
                raise NotFoundError("Файл документа отсутствует на диске", code="file_missing")
            res = extract_text(file_path, doc.file_type)
            path = self._save_extraction(doc.id, res)
            documents_repo.update_document(
                doc.id,
                status="ready" if (res.char_count > 0 and not res.errors) else
                ("error" if res.errors else "ready"),
                extracted_path=str(path),
                char_count=res.char_count,
                page_count=res.page_count,
                extracted_at=utc_now_iso(),
                errors=res.errors,
                warnings=res.warnings,
            )
            return self.get(doc.id)  # type: ignore[return-value]

    def reextract(self, doc_id: str) -> Document:
        """Повторное извлечение текста из сохранённого оригинала."""
        doc = self.get_required(doc_id)
        return self._extract_and_store(doc)

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------
    def get(self, doc_id: str) -> Optional[Document]:
        row = documents_repo.get_document(doc_id)
        return Document.from_row(row) if row else None

    def get_required(self, doc_id: str) -> Document:
        doc = self.get(doc_id)
        if doc is None:
            raise NotFoundError(f"Документ «{doc_id}» не найден", code="document_not_found")
        return doc

    def get_all(self) -> List[Document]:
        return [Document.from_row(r) for r in documents_repo.list_documents()]

    def get_many(self, ids: List[str]) -> List[Document]:
        order = {d: i for i, d in enumerate(ids)}
        docs = [Document.from_row(r) for r in documents_repo.list_documents(include=list(ids))]
        docs.sort(key=lambda d: order.get(d.id, 0))
        return docs

    def load_text(self, doc: Document) -> ExtractionResult:
        """Загрузить извлечённый текст из кэша (или извлечь, если нет)."""
        path = self.extraction_path(doc.id)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return ExtractionResult(
                text=data.get("text", ""),
                char_count=data.get("char_count", 0),
                page_count=data.get("page_count"),
                pages=data.get("pages", []),
                segments=[TextSegment(**s) for s in data.get("segments", [])],
                warnings=data.get("warnings", []),
                errors=data.get("errors", []),
                encoding=data.get("encoding"),
            )
        res = extract_text(Path(doc.path), doc.file_type)
        self._save_extraction(doc.id, res)
        return res

    def delete(self, doc_id: str) -> bool:
        with self._mutex:
            doc = self.get(doc_id)
            if doc is None:
                return False
            upload_dir = Path(doc.path).parent
            ok = documents_repo.delete_document(doc_id)
            shutil.rmtree(upload_dir, ignore_errors=True)
            return ok

    # ------------------------------------------------------------------
    # Преобразование
    # ------------------------------------------------------------------
    def to_out(self, doc: Document) -> DocumentOut:
        return DocumentOut(
            id=doc.id,
            source=doc.source,
            title=doc.title,
            file_type=doc.file_type.upper(),
            file_size=doc.file_size,
            storage_name=doc.storage_name,
            char_count=doc.char_count,
            page_count=doc.page_count,
            status=doc.status,
            content_hash=doc.content_hash,
            warnings=doc.warnings,
            errors=doc.errors,
            created_at=doc.created_at,
            extracted_at=doc.extracted_at,
            has_text=bool(doc.char_count),
        )


loader = DocumentLoader()