"""Демонстрационный MCP-сервер (transport: stdio).

Запускается как отдельный процесс и общается с клиентом через stdin/stdout.
Предоставляет несколько простых инструментов, которые нужны только для
проверки ``list_tools()`` MCP-клиента.

Запуск (обычно выполняет сам MCP-клиент как subprocess):

    cd mcp_server && python mcp_server.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcp.server import MCPServer

mcp = MCPServer(
    name="ai-chat-demo-server",
    version="0.1.0",
    description="Минимальный демонстрационный MCP-сервер для проверки MCP-клиента.",
)


@mcp.tool(description="Echo input message")
def echo(message: str) -> str:
    """Возвращает переданное сообщение без изменений."""
    return message


@mcp.tool(description="Add two numbers")
def add(a: float, b: float) -> float:
    """Возвращает сумму двух чисел."""
    return a + b


@mcp.tool(description="Get current UTC time as an ISO 8601 string")
def get_current_time() -> str:
    """Возвращает текущее время UTC в формате ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    mcp.run(transport="stdio")