"""Модели коллекций и индексов."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class IndexRecord:
    collection_id: str
    strategy: str
    index_id: str
    config_path: str
    config: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "IndexRecord":
        return cls(
            collection_id=row["collection_id"],
            strategy=row["strategy"],
            index_id=row["index_id"],
            config_path=row["config_path"],
            config=json.loads(row.get("config") or "{}"),
            created_at=row.get("created_at") or "",
            updated_at=row.get("updated_at") or "",
        )


@dataclass
class Collection:
    id: str
    name: str
    description: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Collection":
        return cls(
            id=row["id"], name=row["name"], description=row.get("description") or "",
            created_at=row.get("created_at") or "", updated_at=row.get("updated_at") or "",
        )