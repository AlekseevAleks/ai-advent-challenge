"""Логирование запросов к внешнему ИИ-API.

Каждый запрос сохраняется в отдельный JSON-файл в каталоге ``logs/``.
Имя файла формируется по шаблону ``{YYYY-MM-DD}T{HH-MM-SS}_{short_uuid}.json``,
а тот же идентификатор без расширения хранится в сообщениях чата, чтобы
связать их с логом.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = Path(BASE_DIR) / "logs"

# Допустимые символы request_id: буквы, цифры, дефис, подчёркивание, двоеточие и точка.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_\-:.]+$")


def generate_request_id() -> str:
    """Генерирует идентификатор запроса вида ``2026-09-20T14-32-11_a1b2c3d4``.

    Дата и время берутся в UTC, двоеточия в времени заменяются на дефисы
    для совместимости с файловыми системами. Суффикс — первые 8 символов UUID4.
    """
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H-%M-%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{stamp}_{short_uuid}"


def is_valid_request_id(request_id: str) -> bool:
    """Проверяет, что request_id безопасен и не содержит path traversal."""
    if not request_id or not isinstance(request_id, str):
        return False
    if len(request_id) > 128:
        return False
    if ".." in request_id or "/" in request_id or "\\" in request_id:
        return False
    return bool(_REQUEST_ID_RE.match(request_id))


def _log_path(request_id: str) -> Path:
    """Возвращает путь к файлу лога, проверяя безопасность request_id."""
    if not is_valid_request_id(request_id):
        raise ValueError("Недопустимый идентификатор запроса.")
    return LOGS_DIR / f"{request_id}.json"


def save_request_log(request_id: str, data: Dict[str, Any]) -> Path:
    """Сохраняет лог запроса в отдельный JSON-файл и возвращает его путь."""
    path = _log_path(request_id)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return path


def load_request_log(request_id: str) -> Optional[Dict[str, Any]]:
    """Загружает лог запроса по идентификатору или ``None``, если файла нет."""
    try:
        path = _log_path(request_id)
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def mask_api_key(api_key: str) -> str:
    """Возвращает маскированный заголовок авторизации для лога."""
    if not api_key:
        return ""
    return "Bearer sk-***MASKED***"
