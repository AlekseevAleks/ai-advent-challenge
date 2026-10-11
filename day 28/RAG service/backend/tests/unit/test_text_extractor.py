"""Unit-тесты извлечения текста из документов."""

from __future__ import annotations

from pathlib import Path

from app.models.document import ExtractionResult
from app.services.text_extractor import extract_text

from tests.conftest import make_docx, make_pdf


def _write(root: Path, name: str, data: bytes) -> Path:
    p = root / name
    p.write_bytes(data)
    return p


# ---------------------------------------------------------------------------
# TXT / кодировки
# ---------------------------------------------------------------------------

def test_txt_utf8(tmp_path):
    p = _write(tmp_path, "a.txt", "Привет, мир!\nВторая строка\n".encode("utf-8"))
    res = extract_text(p, "txt")
    assert isinstance(res, ExtractionResult)
    assert "Привет, мир!" in res.text
    assert res.char_count == len(res.text)
    assert res.encoding == "utf-8"


def test_txt_cp1251(tmp_path):
    p = _write(tmp_path, "a.txt", "Привет, мир! Ёлка".encode("cp1251"))
    res = extract_text(p, "txt")
    assert "Привет, мир!" in res.text
    assert "Ёлка" in res.text


def test_txt_bom_utf8(tmp_path):
    p = _write(tmp_path, "a.txt", b"\xef\xbb\xbf" + "Привет BOM".encode("utf-8"))
    res = extract_text(p, "txt")
    assert res.text.startswith("Привет BOM")


def test_txt_binary_rejected(tmp_path):
    p = _write(tmp_path, "a.txt", b"\x00\x01\x02binary")
    res = extract_text(p, "txt")
    assert res.errors


def test_empty_txt_warns(tmp_path):
    p = _write(tmp_path, "a.txt", b"\n\n\n")
    res = extract_text(p, "txt")
    assert res.warnings


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def test_markdown_headings_structure(tmp_path):
    md = "# RAG\n\nВведение про RAG.\n\n## Эмбеддинги\n\nВекторы.\n\n## Поиск\n\nFAISS.\n"
    p = _write(tmp_path, "doc.md", md.encode("utf-8"))
    res = extract_text(p, "md")
    assert res.text == md  # Markdown сохраняется без потери
    headings = [s for s in res.segments if s.kind == "heading"]
    assert [(h.level, h.title) for h in headings] == [(1, "RAG"), (2, "Эмбеддинги"), (2, "Поиск")]
    # смещения корректны
    assert headings[0].start == 0
    assert headings[1].start == md.index("## Эмбеддинги")


def test_markdown_ignores_hash_inside_code_fence(tmp_path):
    md = "```python\n# это не заголовок\ndef f():\n    pass\n```\n\n# Настоящий заголовок\n"
    p = _write(tmp_path, "doc.md", md.encode("utf-8"))
    res = extract_text(p, "md")
    headings = [s for s in res.segments if s.kind == "heading"]
    titles = [h.title for h in headings]
    assert titles == ["Настоящий заголовок"]


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def test_pdf_pages_and_page_metadata(tmp_path):
    data = make_pdf(["Page one text", "Page two text"])
    p = _write(tmp_path, "doc.pdf", data)
    res = extract_text(p, "pdf")
    assert res.page_count == 2
    assert "Page one text" in res.text and "Page two text" in res.text
    assert len(res.pages) == 2
    segs = [s for s in res.segments if s.kind == "page"]
    assert [s.page for s in segs] == [1, 2]


def test_pdf_scanned_warning(tmp_path):
    data = make_pdf(["                  "])
    p = _write(tmp_path, "scan.pdf", data)
    res = extract_text(p, "pdf")
    assert res.char_count == 0
    assert any("OCR" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def test_docx_paragraphs_and_headings(tmp_path):
    data = make_docx([(1, "Заголовок"), (0, "Абзац первый."), (2, "Подраздел"), (0, "Абзац второй.")])
    p = _write(tmp_path, "doc.docx", data)
    res = extract_text(p, "docx")
    assert "Заголовок" in res.text
    assert "Абзац первый." in res.text
    assert "Абзац второй." in res.text
    headings = [s for s in res.segments if s.kind == "heading"]
    assert headings and headings[0].level == 1


# ---------------------------------------------------------------------------
# Исходный код
# ---------------------------------------------------------------------------

PY_SAMPLE = '''\
class EmbeddingModel:
    """Модель эмбеддингов."""

    def embed(self, texts):
        return [[1.0]]


def build_index(docs):
    return [len(d) for d in docs]
'''


def test_python_structure(tmp_path):
    p = _write(tmp_path, "mod.py", PY_SAMPLE.encode("utf-8"))
    res = extract_text(p, "py")
    syms = [s for s in res.segments if s.kind == "code_symbol"]
    names = [(s.extra.get("symbol_type"), s.extra.get("symbol_name")) for s in syms]
    assert ("класс", "EmbeddingModel") in names
    assert ("функция", "embed") in names
    assert ("функция", "build_index") in names
    # вложенность: embed внутри класса
    cls = next(s for s in syms if s.extra.get("symbol_name") == "EmbeddingModel")
    fn = next(s for s in syms if s.extra.get("symbol_name") == "embed")
    assert cls.start <= fn.start < cls.end


def test_js_structure(tmp_path):
    js = "class Retriever {\n  fetch(q) {\n    return q;\n  }\n}\nfunction search(query) {\n  return query;\n}\n"
    p = _write(tmp_path, "retr.js", js.encode("utf-8"))
    res = extract_text(p, "js")
    syms = [s for s in res.segments if s.kind == "code_symbol"]
    names = [s.extra.get("symbol_name") for s in syms]
    assert "Retriever" in names
    # метод fetch находится внутри класса Retriever
    cls = next(s for s in syms if s.extra.get("symbol_name") == "Retriever")
    for s in syms:
        if s.extra.get("symbol_name") == "fetch":
            assert cls.start <= s.start < cls.end


def test_csv_rendered(tmp_path):
    p = _write(tmp_path, "d.csv", b"name,value\nalpha,1\nbeta,2\n")
    res = extract_text(p, "csv")
    assert "Строка 1: name, value" in res.text
    assert "Строка 2: alpha, 1" in res.text
    assert "Строка 3: beta, 2" in res.text


def test_json_rendered(tmp_path):
    p = _write(tmp_path, "d.json", b'{"a": [1, 2], "b": {"c": true}}')
    res = extract_text(p, "json")
    assert '"a"' in res.text and '"c": true' in res.text