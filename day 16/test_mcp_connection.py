#!/usr/bin/env python3
"""Полный тестовый сценарий MCP-клиента.

Запускает MCP-сервер (mcp_server.py) как локальный subprocess, подключается
через stdio transport, выполняет initialization, запрашивает список
инструментов через list_tools() и печатает их.

Клиент (ai_chat/app/mcp) остаётся в проекте AI Chat, поэтому его каталог
добавляется в sys.path.

Запуск:

    cd mcp_server
    .venv/bin/python test_mcp_connection.py

При успехе скрипт завершается с кодом 0, при ошибке — с кодом 1.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, List

BASE_DIR = Path(__file__).resolve().parent
SERVER_SCRIPT = BASE_DIR / "mcp_server.py"
# Клиент живёт в проекте ai_chat (app/mcp), добавляем его каталог в sys.path.
AI_CHAT_DIR = BASE_DIR.parent / "ai_chat"
if AI_CHAT_DIR not in sys.path:
    sys.path.insert(0, str(AI_CHAT_DIR))

from app.mcp import MCPClient  # noqa: E402 - после настройки sys.path
from app.mcp.models import MCPTool  # noqa: E402


def _safe_error(exc: Exception) -> str:
    """Возвращает «безопасное» сообщение об ошибке для вывода в консоль."""
    return str(exc) or exc.__class__.__name__


def _print_tools(tools: List[MCPTool]) -> None:
    """Печатает список инструментов: name, description, input schema."""
    if not tools:
        print("  (инструменты не найдены)")
        return
    for index, tool in enumerate(tools, start=1):
        print(f"{index}. {tool.name}")
        print(f"   Description: {tool.description or '(нет описания)'}")
        print("   Input schema:")
        schema = tool.input_schema or {}
        for line in _format_json(schema).splitlines():
            print(f"   {line}")
        if tool.output_schema is not None:
            print("   Output schema:")
            for line in _format_json(tool.output_schema).splitlines():
                print(f"   {line}")
        print()


def _format_json(value: Any) -> str:
    """Форматирует произвольное значение как отступлённый JSON."""
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


async def main() -> int:
    client = MCPClient(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        cwd=BASE_DIR,
    )

    print("Connecting to MCP server...")
    try:
        await client.connect()
    except Exception as exc:  # noqa: BLE001 - верхнеуровневая обработка
        print(f"MCP connection failed:\n{_safe_error(exc)}")
        await client.disconnect()
        return 1
    print("\nMCP connection established.\n")

    try:
        await client.initialize()
    except Exception as exc:  # noqa: BLE001
        print(f"MCP initialization failed:\n{_safe_error(exc)}")
        await client.disconnect()
        return 1
    print("MCP session initialized.\n")

    try:
        tools = await client.list_tools()
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to retrieve MCP tools:\n{_safe_error(exc)}")
        await client.disconnect()
        return 1

    print("Available tools:\n")
    _print_tools(tools)

    print(f"Total tools found: {len(tools)}")
    print("\nMCP test completed successfully.")

    try:
        await client.disconnect()
    except Exception as exc:  # noqa: BLE001
        print(f"MCP disconnect failed:\n{_safe_error(exc)}")
        return 1
    print("Connection closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))