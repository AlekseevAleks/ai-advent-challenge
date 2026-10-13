"""Модели MCP-клиента.

Содержат нейтральные структуры для описания инструментов, полученных
от MCP-сервера через ``list_tools()``. Клиент преобразует объекты
официального MCP SDK в эти модели, не привязывая остальной код
к деталям конкретной версии SDK.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class MCPTool:
    """Описание одного инструмента MCP-сервера.

    Атрибуты:
        name: имя инструмента.
        description: краткое описание.
        input_schema: JSON Schema входных параметров.
        annotations: дополнительные сведения (read_only_hint и т. п.).
        output_schema: описание результата, если сервер его вернул.
    """

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    annotations: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Возвращает представление инструмента в виде словаря."""
        result: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
        if self.annotations is not None:
            result["annotations"] = self.annotations
        if self.output_schema is not None:
            result["output_schema"] = self.output_schema
        return result

    def describe(self) -> str:
        """Формирует компактное текстовое описание инструмента.

        Похоже на то, что выводится консольной утилитой: имя, описание
        и input schema в формате JSON.
        """
        lines = [self.name]
        if self.description:
            lines.append(f"  description: {self.description}")
        lines.append("  input schema:")
        schema = json.dumps(self.input_schema, ensure_ascii=False, indent=4)
        for schema_line in schema.splitlines():
            lines.append(f"    {schema_line}")
        if self.output_schema is not None:
            lines.append("  output schema:")
            out_schema = json.dumps(self.output_schema, ensure_ascii=False, indent=4)
            for schema_line in out_schema.splitlines():
                lines.append(f"    {schema_line}")
        return "\n".join(lines)