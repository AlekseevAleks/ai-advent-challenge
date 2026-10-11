"""Хранение MCP-серверов для страницы «Подключение к MCP».

Серверы хранятся отдельным файлом ``mcp_config.json`` рядом с основным
``config.json`` приложения, чтобы не менять формат пользовательского
конфига AI-чата. Формат файла::

    {
      "address": "http://127.0.0.1:3000/mcp",   # первый сервер (для совместимости)
      "servers": [
        {
          "id": "<uuid>",
          "address": "http://127.0.0.1:3000/mcp",
          "created_at": "...",
          "updated_at": "..."
        }
      ]
    }

Старый формат ``{"address": "..."}`` автоматически мигрирует в список
``servers`` при первом чтении.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ai_chat/app/mcp/settings.py -> ai_chat/mcp_config.json
_MCP_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "mcp_config.json",
)

_DEFAULT_CONFIG: Dict[str, Any] = {"address": "", "servers": []}


def _now() -> str:
    """Возвращает текущее время в UTC в ISO-формате."""
    return datetime.now(timezone.utc).isoformat()


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


def _save_config(data: Dict[str, Any]) -> None:
    """Записывает конфиг MCP в файл."""
    with open(_MCP_CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def load_servers() -> List[Dict[str, Any]]:
    """Возвращает список сохранённых MCP-серверов.

    Мигрирует старый формат ``{"address": ...}`` в список ``servers``:
    адрес получает внутренний UUID и сохраняется обратно в файл.
    """
    data = load_config()
    servers = data.get("servers")
    if isinstance(servers, list):
        valid = [
            server
            for server in servers
            if isinstance(server, dict) and (server.get("address") or "").strip()
        ]
        if len(valid) == len(servers) and valid:
            return valid

    # Миграция старого формата (один адрес в поле "address").
    address = (data.get("address") or "").strip()
    if address:
        server = {
            "id": str(uuid.uuid4()),
            "address": address,
            "created_at": _now(),
            "updated_at": _now(),
        }
        data["servers"] = [server]
        data["address"] = address
        try:
            _save_config(data)
        except OSError:
            pass
        return [server]
    return []


def get_server(server_id: str) -> Optional[Dict[str, Any]]:
    """Возвращает сервер по внутреннему ID или None."""
    for server in load_servers():
        if server.get("id") == server_id:
            return server
    return None


def upsert_server(address: str, server_id: Optional[str] = None) -> Dict[str, Any]:
    """Создаёт или обновляет MCP-сервер и возвращает его.

    - если ``server_id`` задан — обновляет адрес этого сервера;
    - если сервер с таким адресом уже существует — возвращает его
      (повторное сохранение не плодит дубликаты);
    - иначе создаёт новый сервер с внутренним UUID.
    """
    address = (address or "").strip()
    if not address:
        raise ValueError("Адрес MCP-сервера не может быть пустым.")

    data = load_config()
    servers = load_servers()
    now = _now()

    if server_id:
        for server in servers:
            if server.get("id") == server_id:
                server["address"] = address
                server["updated_at"] = now
                data["servers"] = servers
                data["address"] = servers[0]["address"]
                try:
                    _save_config(data)
                except OSError:
                    pass
                return server

    for server in servers:
        if server.get("address") == address:
            return server

    server = {
        "id": str(uuid.uuid4()),
        "address": address,
        "created_at": now,
        "updated_at": now,
    }
    servers.append(server)
    data["servers"] = servers
    data["address"] = servers[0]["address"]
    try:
        _save_config(data)
    except OSError:
        pass
    return server


def delete_server(server_id: str) -> bool:
    """Удаляет сервер по ID. Возвращает True, если сервер был удалён."""
    servers = load_servers()
    remaining = [server for server in servers if server.get("id") != server_id]
    if len(remaining) == len(servers):
        return False
    data = load_config()
    data["servers"] = remaining
    data["address"] = remaining[0]["address"] if remaining else ""
    try:
        _save_config(data)
    except OSError:
        pass
    return True


# --- Обратная совместимость -----------------------------------------------

def load_address() -> str:
    """Возвращает адрес первого сохранённого MCP-сервера (может быть пустым)."""
    servers = load_servers()
    return servers[0]["address"] if servers else ""


def save_address(address: str) -> Optional[Dict[str, Any]]:
    """Сохраняет адрес как отдельный сервер (обратная совместимость)."""
    if not (address or "").strip():
        return None
    return upsert_server(address)