"""Модуль извлечения текста из документов.

Поддерживаемые форматы: PDF, DOCX, TXT, Markdown (MD/MDX), RST, исходный код
(Python, JS, TS и др.), HTML, JSON, YAML, XML, CSV, SQL и другие текстовые.

Все содержимое обрабатывается локально — ничего не отправляется во внешние сервисы.
"""

from __future__ import annotations

import ast
import csv as csv_module
import io
import json
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ..models.document import ExtractionResult, TextSegment

# ---------------------------------------------------------------------------
# Общие помощники
# ---------------------------------------------------------------------------


def _normalize_text(t: str) -> str:
    """Нормализация извлечённого текста без потери содержимого."""
    t = t.replace("\x00", "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"(\n\s*){3,}", "\n\n", t)
    return t


def _compose(items: List[Tuple[str, dict[str, Any]]]) -> Tuple[str, List[dict[str, Any]]]:
    """Собрать текст из частей, расставив переводы строк и вычислив смещения."""
    parts: List[str] = []
    spans: List[dict[str, Any]] = []
    cursor = 0
    for i, (t, meta) in enumerate(items):
        if i > 0:
            parts.append("\n")
            cursor += 1
        start = cursor
        parts.append(t)
        cursor += len(t)
        m = dict(meta)
        m["start"] = start
        m["end"] = start + len(t)
        spans.append(m)
    return "".join(parts), spans


def detect_and_decode(data: bytes) -> Tuple[str, str]:
    """Определить кодировку и декодировать текст (UTF-8/16 и распространённые кодировки)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8-sig"
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16"), "utf-16"
    last_err = None
    for enc in ("utf-8", "cp1251", "cp1252", "iso-8859-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError as e:
            last_err = e
    # cp125x/latin практически все байты декодируют; сюда попадаем только в крайнем случае
    return data.decode("latin-1", errors="replace"), "latin-1 (replace)"


def looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


# ---------------------------------------------------------------------------
# Извлечение по форматам
# ---------------------------------------------------------------------------

def _extract_pdf(path: Path) -> ExtractionResult:
    from pypdf import PdfReader

    warnings: List[str] = []
    errors: List[str] = []
    try:
        reader = PdfReader(str(path))
    except Exception as e:  # noqa: BLE001
        return ExtractionResult(text="", errors=[f"Не удалось открыть PDF: {e}"], warnings=warnings)

    page_count = len(reader.pages)
    items: List[Tuple[str, dict[str, Any]]] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            t = page.extract_text() or ""
        except Exception as e:  # noqa: BLE001
            t = ""
            errors.append(f"Ошибка извлечения текста со стр. {i}: {e}")
        t = _normalize_text(t)
        if t.strip():
            items.append((t, {"kind": "page", "page": i, "title": f"Страница {i}"}))
        elif i == 1 and page_count == 1:
            pass

    text, spans = _compose(items)
    if not text.strip():
        warnings.append(
            "В PDF не найден извлекаемый текст. Похоже, документ содержит сканированные "
            "изображения — для него требуется OCR (в приложении не реализовано)."
        )
    result = ExtractionResult(
        text=text,
        char_count=len(text),
        page_count=page_count,
        pages=[{"page": s.get("page"), "start": s.get("start"), "end": s.get("end")} for s in spans],
        segments=[TextSegment(kind=s["kind"], page=s.get("page"), title=s.get("title"),
                              start=s["start"], end=s["end"]) for s in spans],
        warnings=warnings,
        errors=errors,
        encoding="pdf",
    )
    return result


def _extract_docx(path: Path) -> ExtractionResult:
    from docx import Document as DocxDocument

    warnings: List[str] = []
    errors: List[str] = []
    try:
        d = DocxDocument(str(path))
    except Exception as e:  # noqa: BLE001
        return ExtractionResult(text="", errors=[f"Не удалось открыть DOCX: {e}"], warnings=warnings)

    items: List[Tuple[str, dict[str, Any]]] = []
    for p in d.paragraphs:
        style = (p.style.name or "") if p.style else ""
        txt = p.text.rstrip()
        if not txt:
            continue
        if style.startswith("Heading") or "Заголовок" in style or style in ("Title", "Subtitle"):
            m = re.search(r"(\d+)", style)
            level = int(m.group(1)) if m else 1
            items.append((txt, {"kind": "heading", "level": level, "title": txt[:120]}))
        else:
            items.append((txt, {"kind": "paragraph", "title": None}))
    text, spans = _compose(items)

    if not text.strip():
        warnings.append("В DOCX не найден видимый текст.")
    segments = []
    for s in spans:
        segments.append(
            TextSegment(kind=s["kind"], level=s.get("level"), title=s.get("title"),
                        start=s["start"], end=s["end"])
        )
    return ExtractionResult(
        text=text, char_count=len(text), page_count=None, pages=[], segments=segments,
        warnings=warnings, errors=errors, encoding="docx",
    )


_MD_FENCE_RE = re.compile(r"^[ \t]*(```+|~~~+)")


def _parse_markdown_structure(text: str) -> List[TextSegment]:
    """Заголовки Markdown (# …) с учётом блоков кода, без потери смещений."""
    segments: List[TextSegment] = []
    lines = text.splitlines()
    offsets = _line_offsets(text)
    in_fence = False
    fence_stack: List[str] = []
    for i, line in enumerate(lines):
        fm = _MD_FENCE_RE.match(line)
        if fm:
            if fence_stack and not fm.group(1).startswith(fence_stack[-1]):
                continue  # закрывающий fence другого типа
            if fence_stack:
                fence_stack.pop()
            else:
                fence_stack.append(fm.group(1).strip("`~"))
            continue
        if fence_stack:
            continue
        m = re.match(r"^[ \t]*(#{1,6})[ \t]+(.*?)[ \t]*$", line)
        if not m:
            continue
        title = m.group(2).strip()
        if not title:
            continue
        segments.append(TextSegment(kind="heading", level=len(m.group(1)), title=title,
                                    start=offsets[i] if i < len(offsets) else 0, end=len(text)))
    # setext-заголовки (=== / ---)
    for m in re.finditer(r"^([^\n]{1,200})\n={3,}[ \t]*$", text, re.MULTILINE):
        line_start = text.rfind("\n", 0, m.start()) + 1
        seg = TextSegment(kind="heading", level=1, title=m.group(1).strip(),
                          start=line_start, end=len(text))
        if not any(abs(s.start - seg.start) < 2 for s in segments):
            segments.append(seg)
    segments.sort(key=lambda s: s.start)
    return segments


def _extract_text_format(path: Path, file_type: str) -> ExtractionResult:
    data = path.read_bytes()
    if looks_binary(data):
        return ExtractionResult(text="", errors=["Файл выглядит бинарным и не может быть прочитан как текст."])
    raw, encoding = detect_and_decode(data)
    warnings: List[str] = []
    errors: List[str] = []
    raw = _normalize_text(raw)

    items: List[Tuple[str, dict[str, Any]]] = []
    segments: List[TextSegment] = []

    if file_type == "csv":
        text = _render_csv(raw, errors)
    elif file_type == "json":
        text = _render_json(raw, errors)
    elif file_type in ("markdown", "md", "mdx"):
        text = raw
        segments = _parse_markdown_structure(raw)
    elif file_type == "rst":
        text = raw
        segments = _parse_rst_structure(raw)
    elif file_type == "py":
        text = raw
        segments = parse_python_structure(raw)
    elif file_type in ("js", "jsx", "ts", "tsx"):
        text = raw
        segments = parse_js_ts_structure(raw)
    elif file_type == "html":
        # HTML сохраняем как исходный текст (без потери содержимого)
        text = raw
    elif file_type in ("yml", "yaml"):
        text = raw
    elif file_type == "xml":
        text = raw
    elif file_type == "sql":
        text = raw
    else:
        # TXT, log, ini и прочие исходники — текст как есть
        text = raw

    if not text.strip():
        warnings.append("Документ не содержит текста.")
    if encoding.startswith("latin-1") and encoding == "latin-1 (replace)":
        warnings.append("Кодировка не распознана точно, текст декодирован как Latin-1.")

    return ExtractionResult(
        text=text,
        char_count=len(text),
        page_count=None,
        pages=[],
        segments=segments,
        warnings=warnings,
        errors=errors,
        encoding=encoding,
    )


def _render_csv(raw: str, errors: List[str]) -> str:
    # определение разделителя по частоте во второй строке
    sample = raw.splitlines()[:5]
    sep = ","
    if sample:
        best = ("", -1)
        for cand in (",", ";", "\t", "|"):
            cnt = sum(line.count(cand) for line in sample)
            if cnt > best[1]:
                best = (cand, cnt)
        if best[1] > 0:
            sep = best[0]
    try:
        rows = list(csv_module.reader(io.StringIO(raw), delimiter=sep))
        out = []
        for i, row in enumerate(rows, start=1):
            cells = ", ".join(str(c) for c in row)
            out.append(f"Строка {i}: {cells}")
        return "\n".join(out)
    except Exception as e:  # noqa: BLE001
        errors.append(f"Не удалось разобрать CSV ({e}); сохранён исходный текст.")
        return raw


def _render_json(raw: str, errors: List[str]) -> str:
    try:
        obj = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        errors.append(f"Некорректный JSON ({e}); сохранён исходный текст.")
        return raw
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _parse_rst_structure(text: str) -> List[TextSegment]:
    """Разделы RST: строка с подчёркиванием (=, -, ~, ^)."""
    segments: List[TextSegment] = []
    lines = text.splitlines()
    offsets = _line_offsets(text)
    for i, line in enumerate(lines):
        if i + 1 >= len(lines):
            continue
        nxt = lines[i + 1]
        if not nxt:
            continue
        if re.match(r"^[=\-~^\"']{3,}[ \t]*$", nxt) and line.strip():
            segments.append(TextSegment(kind="heading", level=1, title=line.strip(),
                                        start=offsets[i], end=len(text)))
    # вложенность по символу подчёркивания
    levels = {"=": 1, "-": 2, "~": 3, "^": 4, '"': 5, "'": 6}
    segments.sort(key=lambda s: s.start)
    prev = None
    for seg in segments:
        idx = seg.start
        line_i = text[:idx].count("\n")
        if line_i + 1 < len(lines):
            under = lines[line_i + 1]
            if under:
                ch = under[0]
                if ch in levels:
                    seg.level = levels[ch]
    return segments


# ---------------------------------------------------------------------------
# Структура исходного кода
# ---------------------------------------------------------------------------

def _line_offsets(text: str) -> List[int]:
    offsets = [0]
    for m in re.finditer("\n", text):
        offsets.append(m.end())
    return offsets


def parse_python_structure(text: str) -> List[TextSegment]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    offsets = _line_offsets(text)
    segments: List[TextSegment] = []

    def text_end(line_idx: int) -> int:
        idx = line_idx + 1
        if idx < len(offsets):
            return offsets[idx]
        return len(text)

    def walk(node: ast.AST, level: int) -> None:
        for item in ast.iter_child_nodes(node):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start_line = max(item.lineno - 1, 0)
                end_line = (item.end_lineno or item.lineno) - 1
                kind = "класс" if isinstance(item, ast.ClassDef) else "функция"
                segments.append(TextSegment(
                    kind="code_symbol",
                    title=item.name,
                    level=level + 1,
                    start=offsets[start_line] if start_line < len(offsets) else 0,
                    end=text_end(end_line),
                    extra={"symbol_type": kind, "symbol_name": item.name},
                ))
                walk(item, level + 1)

    walk(tree, 0)
    segments.sort(key=lambda s: s.start)
    return segments


_JS_FN_RE = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\("
)
_JS_CLASS_RE = re.compile(r"(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)\b")
_JS_ARROW_RE = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")
_JS_METHOD_RE = re.compile(r"^\s{2,}(?:async\s+)?(?:get\s+|set\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")


def _js_span_end(text: str, search_from: int) -> int:
    """Найти конец блока `{...}` начиная с первого `{` не раньше search_from."""
    open_idx = text.find("{", search_from)
    if open_idx == -1:
        return search_from
    depth = 0
    i = open_idx
    in_str = None
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in "\"'`":
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def parse_js_ts_structure(text: str) -> List[TextSegment]:
    segments: List[TextSegment] = []
    lines = text.splitlines()
    offsets = _line_offsets(text)

    def add(kind: str, name: str, start: int, end: int, level: int) -> None:
        segments.append(TextSegment(kind="code_symbol", title=name, level=level,
                                    start=start, end=end,
                                    extra={"symbol_type": kind, "symbol_name": name}))

    for i, line in enumerate(lines):
        start = offsets[i] if i < len(offsets) else 0
        m = _JS_CLASS_RE.search(line)
        if m:
            add("класс", m.group(1), start, _js_span_end(text, start), 1)
            continue
        m = _JS_FN_RE.search(line)
        if m:
            add("функция", m.group(1), start, _js_span_end(text, start), 1)
            continue
        m = _JS_ARROW_RE.search(line)
        if m:
            add("функция", m.group(1), start, _js_span_end(text, start), 1)
            continue
        if line.startswith((" ", "\t")):
            m = _JS_METHOD_RE.search(line)
            if m and m.group(1) not in ("if", "for", "while", "switch", "catch", "else"):
                add("метод", m.group(1), start, _js_span_end(text, start), 2)
    segments.sort(key=lambda s: s.start)
    # убрать вложенные дубли (методы, попавшие внутрь класса)
    dedup: List[TextSegment] = []
    for seg in segments:
        if any(o.start <= seg.start < o.end and o is not seg for o in segments):
            continue
        dedup.append(seg)
    return dedup


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def extract_text(file_path: Path, file_type: str) -> ExtractionResult:
    """Извлечь текст из файла по расширению (file_type без точки, в нижнем регистре)."""
    ft = (file_type or "").lower().lstrip(".")
    if ft == "pdf":
        return _extract_pdf(Path(file_path))
    if ft == "docx":
        return _extract_docx(Path(file_path))
    if ft in ("md", "mdx", "markdown"):
        res = _extract_text_format(Path(file_path), "md")
        return res
    return _extract_text_format(Path(file_path), ft)