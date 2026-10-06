"""Сгенерированные идентификаторы."""

from __future__ import annotations

import uuid


def new_id(prefix: str, length: int = 8) -> str:
    """Короткий уникальный идентификатор вида `prefix_ab12cd34`.

    Сгенерированные идентификаторы уникальны практически гарантированно
    (128-битный UUID, первые `length` hex-символов).
    """
    return f"{prefix}_{uuid.uuid4().hex[:length]}"


def new_uuid() -> str:
    return uuid.uuid4().hex


def make_chunk_id() -> str:
    return f"chunk_{uuid.uuid4().hex[:12]}"