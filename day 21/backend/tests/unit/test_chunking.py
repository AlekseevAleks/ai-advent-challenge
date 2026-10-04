"""Unit-тесты обеих стратегий chunking и метаданных чанков."""

from __future__ import annotations

from app.models.document import Document
from app.schemas.indexing import FixedSizeParams, StructuralParams
from app.services.chunking import chunk_fixed_size, chunk_structural

SAMPLE_MD = """\
# Документация проекта

## Установка

Установите зависимости командой pip install.

## Запуск

### Режим разработки

Запустите сервер командой uvicorn.

### Режим продакшн

Используйте docker compose up.

## Индексация

Разбейте документы на чанки и постройте индекс.

## Заключение

Проект готов к использованию.
"""

PY_CODE = """\
class Retriever:
    def search(self, query):
        results = []
        for doc in self.docs:
            if query in doc.text:
                results.append(doc)
        return results

    def rank(self, items):
        return sorted(items)

def build_index(docs):
    return [d.word_count() for d in docs]

TOP_LEVEL = 42
"""


def _doc(document_id="doc_1", text=SAMPLE_MD, segments=None, pages=None):
    d = Document(
        id=document_id, original_name="doc.md", storage_name="doc.md",
        file_type="md", file_size=len(text), path="",
        content_hash="h", status="ready", char_count=len(text),
    )
    if segments is not None:
        from app.models.document import TextSegment

        setattr(d, "_segments", segments)
    if pages:
        setattr(d, "_pages", pages)
    setattr(d, "_text", text)
    return d


# ---------------------------------------------------------------------------
# Fixed-size chunking
# ---------------------------------------------------------------------------

def test_fixed_size_basic():
    text = "Слово " * 200  # 1200 символов
    doc = _doc(text=text)
    chunks = chunk_fixed_size(doc, text, FixedSizeParams(chunk_size=300, overlap=50))
    assert chunks
    assert all(c.char_count <= 300 for c in chunks)
    # перекрытие: следующий чанк начинается не позже конца предыдущего минус overlap
    for a, b in zip(chunks, chunks[1:]):
        assert a.end_offset - b.start_offset <= 50


def test_fixed_size_overlap_validation():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FixedSizeParams(chunk_size=100, overlap=200)


def test_fixed_size_empty_document():
    doc = _doc(text="   \n\n  ")
    chunks = chunk_fixed_size(doc, "   \n\n  ", FixedSizeParams(chunk_size=500, overlap=50))
    assert chunks == []


def test_fixed_size_respects_max_not_exceeded():
    text = ("Предложение. " * 300)
    doc = _doc(text=text)
    chunks = chunk_fixed_size(doc, text, FixedSizeParams(chunk_size=700, overlap=100))
    assert chunks
    assert max(c.char_count for c in chunks) <= 700


def test_fixed_size_tokens_requires_tiktoken():
    import pytest

    try:
        import tiktoken  # noqa: F401
        pytest.skip("tiktoken установлен — проверка недоступности неактуальна")
    except ImportError:
        doc = _doc()
        with pytest.raises(ValueError, match="tiktoken"):
            chunk_fixed_size(doc, SAMPLE_MD, FixedSizeParams(chunk_size=100, overlap=10, unit="tokens"))


def test_fixed_size_chunk_metadata():
    text = "Слово " * 100
    doc = _doc(text=text)
    chunks = chunk_fixed_size(doc, text, FixedSizeParams(chunk_size=200, overlap=20))
    meta = chunks[0].to_metadata("collection_1", "nomic-embed-text", 1)
    for key in ("chunk_id", "document_id", "source", "title", "section", "text",
                "chunk_index", "chunking_strategy", "start_offset", "end_offset",
                "char_count", "embedding_model", "collection_id", "index_version"):
        assert key in meta
    assert meta["chunking_strategy"] == "fixed_size"
    assert meta["collection_id"] == "collection_1"
    assert meta["embedding_model"] == "nomic-embed-text"


def test_chunk_ids_unique():
    text = "Слово " * 300
    doc = _doc(text=text)
    chunks = chunk_fixed_size(doc, text, FixedSizeParams(chunk_size=500, overlap=50))
    ids = {c.chunk_id for c in chunks}
    assert len(ids) == len(chunks)


# ---------------------------------------------------------------------------
# Structural chunking
# ---------------------------------------------------------------------------

def test_structural_by_markdown_headings():
    from app.services.text_extractor import _parse_markdown_structure

    text = _normalize(SAMPLE_MD)
    doc = _doc(text=text, segments=_parse_markdown_structure(text))
    chunks = chunk_structural(doc, text, StructuralParams(max_chunk_size=500, min_chunk_size=100))
    titles = [c.title for c in chunks]
    assert set(titles) == {"doc.md"}
    # путь заголовков должен быть в section хотя бы одного чанка
    assert any(c.section and "Документация проекта" in c.section for c in chunks)
    assert any(c.section and "Запуск" in c.section for c in chunks)
    # содержимое разных файлов не объединяется: все чанки одного документа
    assert all(c.document_id == "doc_1" for c in chunks)


def test_structural_oversized_section_split():
    big = "# Раздел\n\n" + ("Очень длинный абзац для проверки рекурсивного деления. " * 120)
    from app.services.text_extractor import _parse_markdown_structure

    text = _normalize(big)
    doc = _doc(text=text, segments=_parse_markdown_structure(text))
    chunks = chunk_structural(doc, text, StructuralParams(max_chunk_size=300, min_chunk_size=50))
    assert len(chunks) > 5
    assert max(c.char_count for c in chunks) <= 300
    # все чанки принадлежат разделу «Раздел»
    assert all(c.section for c in chunks)


def test_structural_small_sections_merged():
    md = "# A\n\nКороткий.\n\n# B\n\nЕщё короткий.\n\n# C\n\nТретий короткий.\n"
    from app.services.text_extractor import _parse_markdown_structure

    text = _normalize(md)
    doc = _doc(text=text, segments=_parse_markdown_structure(text))
    chunks = chunk_structural(doc, text, StructuralParams(max_chunk_size=500, min_chunk_size=200))
    # маленькие разделы объединяются: должны получиться укрупнённые чанки
    assert len(chunks) < 3


def test_structural_no_headings_fallback_paragraphs():
    text = "Параграф один. Слова.\n\nПараграф два. Слова.\n\n" * 20
    doc = _doc(text=text, segments=[])
    chunks = chunk_structural(doc, text, StructuralParams(max_chunk_size=400, min_chunk_size=80))
    assert chunks
    assert max(c.char_count for c in chunks) <= 400


def test_structural_python_code_symbols():
    from app.services.text_extractor import parse_python_structure

    text = _normalize(PY_CODE)
    doc = _doc(text=text, segments=parse_python_structure(text))
    chunks = chunk_structural(doc, text, StructuralParams(max_chunk_size=300, min_chunk_size=50))
    assert chunks
    syms = {(c.symbol_name, c.symbol_type) for c in chunks if c.symbol_name}
    assert ("Retriever", "класс") in syms
    assert ("build_index", "функция") in syms
    assert any(c.section and "Retriever" in (c.section or "") for c in chunks)


def test_structural_pdf_pages():
    from app.models.document import TextSegment

    text = "Страница один текст.\nСтраница два текст."
    pages = [
        {"page": 1, "start": 0, "end": text.index("Страница два")},
        {"page": 2, "start": text.index("Страница два"), "end": len(text)},
    ]
    doc = _doc(text=text, segments=[
        TextSegment(kind="page", page=1, start=0, end=pages[0]["end"]),
        TextSegment(kind="page", page=2, start=pages[1]["start"], end=len(text)),
    ], pages=pages)
    chunks = chunk_structural(doc, text, StructuralParams(max_chunk_size=500, min_chunk_size=50))
    assert any(c.page_start == 1 for c in chunks)
    assert any(c.page_start == 2 for c in chunks)


def test_structural_empty_document():
    doc = _doc(text="\n\n", segments=[])
    chunks = chunk_structural(doc, "\n\n", StructuralParams(max_chunk_size=200, min_chunk_size=50))
    assert chunks == []


def _normalize(t: str) -> str:
    import re

    return re.sub(r"(\n\s*){3,}", "\n\n", t)