"""Хранилище инструментов MCP-серверов в памяти приложения.

Каждый сервер, добавленный на странице «Подключение к MCP», имеет
внутренний ID (UUID) и адрес. Инструменты, полученные с сервера,
кэшируются здесь, чтобы агент:

- не дёргал MCP-сервер при каждом сообщении (достаточно одного
  успешного ``list_tools()``);
- распределял вызовы по подходящему серверу: инструмент ищется
  по имени во всех закэшированных серверах.

Кэш живёт только в памяти процесса: при перезапуске приложение
запросит инструменты заново. Соединения с серверами здесь НЕ
хранятся — они открываются на время запроса в ``main.py``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import MCPTool


@dataclass
class ServerTools:
    """Закэшированный набор инструментов одного MCP-сервера."""

    server_id: str
    address: str
    tools: List[MCPTool] = field(default_factory=list)
    openai_tools: List[Dict[str, Any]] = field(default_factory=list)
    fetched_at: Optional[str] = None
    error: Optional[str] = None


class MCPRegistry:
    """Потокобезопасный in-memory кэш инструментов MCP-серверов."""

    def __init__(self) -> None:
        self._entries: Dict[str, ServerTools] = {}
        self._by_name: Dict[str, str] = {}
        self._lock = threading.Lock()

    # --- чтение ---------------------------------------------------------

    def get(self, server_id: str) -> Optional[ServerTools]:
        """Возвращает закэшированные тулы сервера (или None)."""
        with self._lock:
            return self._entries.get(server_id)

    def all(self) -> List[ServerTools]:
        """Возвращает все закэшированные записи."""
        with self._lock:
            return list(self._entries.values())

    def find_server_for_tool(self, name: str) -> Optional[ServerTools]:
        """Находит сервер, объявивший инструмент с указанным именем.

        Если имя объявлено несколькими серверами, побеждает первый
        (порядок серверов из настроек сохраняется при вставке).
        """
        with self._lock:
            server_id = self._by_name.get(name)
            if server_id is None:
                return None
            return self._entries.get(server_id)

    # --- запись ---------------------------------------------------------

    def set(
        self,
        server_id: str,
        address: str,
        tools: List[MCPTool],
        openai_tools: List[Dict[str, Any]],
    ) -> ServerTools:
        """Сохраняет (или обновляет) тулы сервера в кэше."""
        entry = ServerTools(
            server_id=server_id,
            address=address,
            tools=list(tools),
            openai_tools=list(openai_tools),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._entries[server_id] = entry
            self._rebuild_index_locked()
        return entry

    def set_error(self, server_id: str, address: str, error: str) -> None:
        """Помечает сервер как недоступный (тулы не получены)."""
        with self._lock:
            previous = self._entries.get(server_id)
            entry = ServerTools(
                server_id=server_id,
                address=address,
                tools=list(previous.tools) if previous else [],
                openai_tools=list(previous.openai_tools) if previous else [],
                fetched_at=previous.fetched_at if previous else None,
                error=error,
            )
            self._entries[server_id] = entry
            self._rebuild_index_locked()

    def remove(self, server_id: str) -> None:
        """Удаляет сервер из кэша (используется при удалении сервера)."""
        with self._lock:
            self._entries.pop(server_id, None)
            self._rebuild_index_locked()

    def clear(self) -> None:
        """Полностью очищает кэш (например, при смене адреса)."""
        with self._lock:
            self._entries.clear()
            self._by_name.clear()

    # --- вспомогательное ------------------------------------------------

    def _rebuild_index_locked(self) -> None:
        """Перестраивает индекс «имя инструмента -> server_id»."""
        index: Dict[str, str] = {}
        for entry in self._entries.values():
            for tool in entry.tools:
                if tool.name not in index:
                    index[tool.name] = entry.server_id
        self._by_name = index


# Единый реестр приложения: один на процесс.
registry = MCPRegistry()