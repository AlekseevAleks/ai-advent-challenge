"""Работа с локальным файлом конфигурации config.json.

Модуль отвечает за чтение, запись и маскирование настроек подключения
к OpenAI-совместимому API (адрес, ключ, модель по умолчанию).
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG: Dict[str, Any] = {
    "api_url": "https://api.openai.com/v1",
    "api_key": "",
    "default_model": "gpt-4o-mini",
}

_lock = threading.RLock()


def _ensure_file() -> None:
    """Создаёт config.json со значениями по умолчанию, если файла нет."""
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(DEFAULT_CONFIG, fh, ensure_ascii=False, indent=2)


def _read_config() -> Dict[str, Any]:
    """Читает конфиг с диска без захвата блокировки (для внутреннего использования)."""
    _ensure_file()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {**DEFAULT_CONFIG, **data}


def load_config() -> Dict[str, Any]:
    """Читает конфиг с диска, дополняя отсутствующие поля значениями по умолчанию."""
    with _lock:
        return _read_config()


def save_config(api_url: str, api_key: str, default_model: str) -> Dict[str, Any]:
    """Сохраняет конфиг на диск.

    Пустой ``api_key`` не затирает уже сохранённый ключ — это позволяет
    фронтенду отправлять маскированное значение без потери секрета.
    """
    with _lock:
        current = _read_config()
        new_key = api_key.strip() if api_key else ""
        if not new_key or new_key.startswith("sk-...") or "•" in new_key:
            new_key = current.get("api_key", "")

        config = {
            "api_url": (api_url or DEFAULT_CONFIG["api_url"]).strip().rstrip("/"),
            "api_key": new_key,
            "default_model": (default_model or DEFAULT_CONFIG["default_model"]).strip(),
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(config, fh, ensure_ascii=False, indent=2)
        return config


def mask_key(api_key: str) -> str:
    """Возвращает маскированный вид ключа, например ``sk-...abcd``."""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "•" * len(api_key)
    return f"{api_key[:3]}...{api_key[-4:]}"


def public_config() -> Dict[str, Any]:
    """Конфиг для отдачи на фронтенд: ключ только в маскированном виде."""
    config = load_config()
    return {
        "api_url": config.get("api_url", ""),
        "api_key_masked": mask_key(config.get("api_key", "")),
        "has_key": bool(config.get("api_key")),
        "default_model": config.get("default_model", ""),
    }
