"""MCP-клиент на официальном Python MCP SDK.

Поддерживает два транспорта:

- ``stdio``: клиент запускает MCP-сервер как локальный subprocess
  (``command``/``args``);
- ``streamable-http``: клиент подключается к уже запущенному серверу
  по адресу (``url``, например ``http://127.0.0.1:8080/mcp``) без авторизации.

Клиент выполняет initialization и умеет запрашивать список инструментов.
Этот модуль изолирован от остального приложения: он не используется
ни AI-чатом, ни PromptBuilder, ни памятью.
"""

from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from .models import MCPTool

# Таймауты HTTP-подключения: соединение должно падать быстро,
# но у MCP-операций (initialize, list_tools) остаётся запас.
_HTTP_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class MCPClient:
    """Клиент для подключения к MCP-серверу.

    Использование (stdio):

        client = MCPClient(command=sys.executable, args=["mcp_server/mcp_server.py"])
        await client.connect()
        await client.initialize()
        tools = await client.list_tools()
        await client.disconnect()

    Использование (по адресу):

        client = MCPClient.for_url("http://127.0.0.1:8080/mcp")
        await client.connect()
        ...
    """

    def __init__(
        self,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        cwd: Optional[Path] = None,
        url: Optional[str] = None,
    ) -> None:
        self._command = command
        self._args = list(args or [])
        self._cwd = cwd
        self._url = (url or "").strip()
        self._server_params = (
            StdioServerParameters(
                command=self._command,
                args=self._args,
                cwd=str(cwd) if cwd is not None else None,
            )
            if not self._url
            else None
        )
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
        self._initialized = False

    @classmethod
    def for_url(cls, url: str) -> "MCPClient":
        """Возвращает клиента, подключающегося к MCP-серверу по адресу."""
        return cls(url=url)

    async def connect(self) -> None:
        """Устанавливает transport + сессию с MCP-сервером.

        Шаг выполняется до initialization. Если сервер недоступен,
        поднимается исключение (обычно ``OSError`` / ``httpx.HTTPError``).
        """
        self._stack = AsyncExitStack()
        if self._url:
            http_client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
            await self._stack.enter_async_context(http_client)
            streams = await self._stack.enter_async_context(
                streamable_http_client(self._url, http_client=http_client)
            )
        else:
            if not self._command:
                raise RuntimeError(
                    "MCPClient: укажите command (stdio) или url (streamable-http)."
                )
            streams = await self._stack.enter_async_context(
                stdio_client(self._server_params)
            )
        read_stream, write_stream = streams
        self._session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        self._initialized = False

    async def initialize(self) -> Dict[str, Any]:
        """Выполняет protocol initialization (handshake) с MCP-сервером."""
        if self._session is None:
            raise RuntimeError("MCPClient: сессия не создана, сначала вызовите connect().")
        result = await self._session.initialize()
        self._initialized = True
        return result.to_dict() if hasattr(result, "to_dict") else dict(result)

    async def list_tools(self) -> List[MCPTool]:
        """Возвращает список инструментов, объявленных MCP-сервером."""
        if self._session is None:
            raise RuntimeError("MCPClient: сессия не создана, сначала вызовите connect().")
        if not self._initialized:
            await self.initialize()
        list_result = await self._session.list_tools()
        return [self._to_model(tool) for tool in list_result.tools]

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Вызывает инструмент MCP-сервера и возвращает результат.

        Результат приводится к JSON-совместимому словарю:
        ``{"content": ..., "structured_content": ..., "is_error": bool}``.
        """
        if self._session is None:
            raise RuntimeError("MCPClient: сессия не создана, сначала вызовите connect().")
        if not self._initialized:
            await self.initialize()
        result = await self._session.call_tool(name, arguments or {})
        is_error = bool(getattr(result, "is_error", False))
        structured = getattr(result, "structured_content", None)
        return {
            "name": name,
            "arguments": arguments or {},
            "content": self._result_text(result),
            "structured_content": structured,
            "is_error": is_error,
        }

    @staticmethod
    def _result_text(result: Any) -> str:
        """Собирает текстовое представление результата инструмента."""
        content = getattr(result, "content", None)
        if not content:
            return ""
        parts = []
        for block in content:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(text)
        return "\n".join(parts)


    async def disconnect(self) -> None:
        """Корректно закрывает сессию, transport и останавливает процесс сервера.

        Ошибки закрытия не пробрасываются: если подключение уже упало,
        ``aclose()`` может повторить исходную ошибку, и она не должна
        перекрывать основное исключение (``try/finally`` в вызывающем коде).
        """
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception:  # noqa: BLE001 - закрытие не должно маскировать основную ошибку
                pass
        self._stack = None
        self._session = None
        self._initialized = False

    @classmethod
    def for_script(cls, script_path: Path) -> "MCPClient":
        """Возвращает клиента, запускающего указанный скрипт-сервер.

        Удобно для тестовых скриптов: сервер запускается тем же
        интерпретатором, что и клиент.
        """
        return cls(command=sys.executable, args=[str(script_path)])

    @staticmethod
    def _to_model(tool: Any) -> MCPTool:
        """Преобразует объект Tool из MCP SDK в нейтральную модель MCPTool."""
        annotations: Optional[Dict[str, Any]] = None
        raw_annotations = getattr(tool, "annotations", None)
        if raw_annotations is not None:
            if hasattr(raw_annotations, "model_dump"):
                annotations = raw_annotations.model_dump(exclude_none=True)
            else:
                annotations = dict(raw_annotations)

        output_schema: Optional[Dict[str, Any]] = None
        raw_output = getattr(tool, "output_schema", None)
        if raw_output is not None:
            output_schema = dict(raw_output)

        return MCPTool(
            name=tool.name,
            description=tool.description or "",
            input_schema=dict(getattr(tool, "input_schema", {}) or {}),
            annotations=annotations,
            output_schema=output_schema,
        )