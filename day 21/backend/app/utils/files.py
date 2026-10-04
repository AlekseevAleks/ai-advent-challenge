"""Безопасная работа с файлами и путями."""

from __future__ import annotations

import re
from pathlib import Path

# Недопустимые символы заменяются на подчёркивание
_UNSAFE = re.compile(r"[^A-Za-zА-Яа-яЁё0-9._\[\]()\-\u00C0-\u024F ]")


def safe_filename(name: str) -> str:
    """Очистить имя файла от path-обхода и небезопасных символов."""
    name = (name or "file").replace("\\", "/").split("/")[-1].strip()
    name = _UNSAFE.sub("_", name)
    name = name.strip(" .")
    return name or "file"


def unique_storage_filename(original_name: str, existing_names: set[str]) -> str:
    """Обеспечить уникальность имени среди `existing_names` (суффикс `_N`)."""
    name = safe_filename(original_name)
    if name not in existing_names:
        return name
    stem, dot, ext = name.rpartition(".")
    i = 1
    if dot:
        while f"{stem}_{i}.{ext}" in existing_names:
            i += 1
        return f"{stem}_{i}.{ext}"
    while f"{name}_{i}" in existing_names:
        i += 1
    return f"{name}_{i}"


def is_within(base: Path, target: Path) -> bool:
    """Проверка, что target находится внутри base (защита от path traversal)."""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def ensure_safe_relative_path(base: Path, candidate: str) -> Path:
    """Вернуть безопасный путь внутри base или бросить ValueError."""
    p = (base / candidate).resolve()
    if not is_within(base, p):
        raise ValueError("Недопустимый путь")
    return p