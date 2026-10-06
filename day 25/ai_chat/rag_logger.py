"""Логирование запросов и ответов RAG-сервиса.

Каждый RAG-запрос сохраняется в отдельный JSON-файл в каталоге ``logs/``
с именем ``rag_{request_id}.json`` (идентификатор генерируется так же,
как для запросов к ИИ-API, но с префиксом ``rag_``, чтобы файлы не
пересекались). Кнопка «Запрос RAG» в интерфейсе открывает этот лог.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from request_logger import generate_request_id, is_valid_request_id

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = Path(BASE_DIR) / "logs"


def generate_rag_request_id() -> str:
    """Генерирует идентификатор RAG-запроса вида ``2026-10-04T12-00-00_a1b2c3d4``."""
    return generate_request_id()


def save_rag_log(request_id: str, data: Dict[str, Any]) -> Path:
    """Сохраняет лог RAG-запроса в отдельный JSON-файл и возвращает его путь."""
    if not is_valid_request_id(request_id):
        raise ValueError("Недопустимый идентификатор RAG-запроса.")
    path = LOGS_DIR / f"rag_{request_id}.json"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return path


def load_rag_log(request_id: str) -> Optional[Dict[str, Any]]:
    """Загружает лог RAG-запроса по идентификатору или ``None``, если его нет."""
    if not is_valid_request_id(request_id):
        return None
    path = LOGS_DIR / f"rag_{request_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None