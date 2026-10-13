"""Трансляция MCP-инструментов в формат OpenAI function calling.

Отдельный модуль, чтобы позже легко добавить поддержку другого провайдера.
Используется AI-чатом: инструменты с MCP-сервера превращаются в ``tools``
для ``chat/completions``, а аргументы ``tool_calls`` валидируются по
JSON Schema из ``input_schema`` до вызова MCP-сервера.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import jsonschema

from .models import MCPTool


def to_openai_tools(tools: List[MCPTool]) -> List[Dict[str, Any]]:
    """Преобразует список MCP-инструментов в формат OpenAI ``tools``.

    Правила:
    - ``name``        -> ``function.name``;
    - ``description`` -> ``function.description``;
    - ``input_schema``-> ``function.parameters`` (содержимое не меняется);
    - каждый инструмент оборачивается в ``{"type": "function", ...}``.
    """
    result: List[Dict[str, Any]] = []
    for tool in tools:
        schema = tool.input_schema or {"type": "object", "properties": {}}
        result.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": schema,
                },
            }
        )
    return result


def find_tool(tools: List[MCPTool], name: str) -> Optional[MCPTool]:
    """Возвращает инструмент по имени из списка MCP-инструментов."""
    for tool in tools:
        if tool.name == name:
            return tool
    return None


def validate_arguments(tool: MCPTool, arguments: Any) -> Tuple[bool, Optional[str]]:
    """Проверяет аргументы по JSON Schema инструмента.

    Возвращает ``(ok, error_message)``; при неудаче MCP-сервер
    не вызывается, а ошибка возвращается модели.
    """
    schema = tool.input_schema
    if not schema:
        return True, None
    if not isinstance(arguments, dict):
        return False, f"arguments должны быть объектом, получено {type(arguments).__name__}"
    try:
        jsonschema.validate(arguments, schema)
    except jsonschema.ValidationError as exc:
        return False, f"аргументы не прошли валидацию: {exc.message}"
    except jsonschema.SchemaError as exc:
        return False, f"некорректная схема инструмента: {exc.message}"
    return True, None