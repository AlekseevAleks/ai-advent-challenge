"""Работа с локальным файлом конфигурации config.json.

Модуль отвечает за чтение, запись и маскирование настроек подключения
к OpenAI-совместимому API (адрес, ключ, модель по умолчанию), а также
настроек RAG-сервиса (адрес и выбранная коллекция).
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
    "rag_url": "http://localhost:8000",
    "rag_collection": "",
    "rag_strategy": "",
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


def save_config(
    api_url: str,
    api_key: str,
    default_model: str,
    rag_url: str = "",
) -> Dict[str, Any]:
    """Сохраняет конфиг на диск.

    Пустой ``api_key`` не затирает уже сохранённый ключ — это позволяет
    фронтенду отправлять маскированное значение без потери секрета.
    RAG-настройки при сохранении основной формы не затрагиваются: пустой
    ``rag_url`` оставляет сохранённое значение без изменений.
    """
    with _lock:
        current = _read_config()
        new_key = api_key.strip() if api_key else ""
        # Маскированный ключ (например, "sk-...abcd" или "pza...u_W3")
        # не должен затирать настоящий: фронт отправляет маску при
        # сохранении настроек без изменения ключа.
        if not new_key or "..." in new_key or "•" in new_key:
            new_key = current.get("api_key", "")

        config = {
            "api_url": (api_url or DEFAULT_CONFIG["api_url"]).strip().rstrip("/"),
            "api_key": new_key,
            "default_model": (default_model or DEFAULT_CONFIG["default_model"]).strip(),
            "rag_url": (
                (rag_url or current.get("rag_url", DEFAULT_CONFIG["rag_url"])).strip().rstrip("/")
            ),
            "rag_collection": current.get("rag_collection", ""),
            "rag_strategy": current.get("rag_strategy", ""),
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(config, fh, ensure_ascii=False, indent=2)
        return config


def save_rag_config(rag_url: str, rag_collection: str = "", rag_strategy: str = "") -> Dict[str, Any]:
    """Обновляет только RAG-настройки, не трогая остальной конфиг.

    Используется кнопкой «Сохранить» в секции RAG: сохраняются адрес
    сервера, выбранная коллекция и стратегия chunking, остальные поля
    (API-ключ и т. п.) остаются без изменений. Значения переживают
    перезапуск агента.
    """
    with _lock:
        current = _read_config()
        current["rag_url"] = (rag_url or DEFAULT_CONFIG["rag_url"]).strip().rstrip("/")
        current["rag_collection"] = (rag_collection or "").strip()
        current["rag_strategy"] = (rag_strategy or "").strip()
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(current, fh, ensure_ascii=False, indent=2)
        return current


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
        "rag_url": config.get("rag_url", ""),
        "rag_collection": config.get("rag_collection", ""),
        "rag_strategy": config.get("rag_strategy", ""),
    }