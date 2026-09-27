"""Хранение адреса MCP-сервера для страницы «Подключение к MCP».

Адрес хранится отдельным файлом ``mcp_config.json`` рядом с основным
``config.json`` приложения, чтобы не менять формат пользовательского
конфига AI-чата.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

# ai_chat/app/mcp/settings.py -> ai_chat/mcp_config.json
_MCP_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "mcp_config.json",
)

_DEFAULT_CONFIG: Dict[str, Any] = {"address": ""}


def load_config() -> Dict[str, Any]:
    """Читает сохранённый конфиг MCP (при отсутствии файла — пустой)."""
    try:
        with open(_MCP_CONFIG_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return dict(_DEFAULT_CONFIG)
        return data
    except (OSError, ValueError):
        return dict(_DEFAULT_CONFIG)


def load_address() -> str:
    """Возвращает сохранённый адрес MCP-сервера (может быть пустым)."""
    return (load_config().get("address") or "").strip()


def save_address(address: str) -> None:
    """Сохраняет адрес MCP-сервера, не трогая остальные файлы конфига."""
    data = load_config()
    data["address"] = (address or "").strip()
    with open(_MCP_CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)