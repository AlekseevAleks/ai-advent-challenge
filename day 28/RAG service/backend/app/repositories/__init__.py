"""Репозитории данных (SQLite, документы, коллекции, индексы, задания, настройки)."""

from .db import (  # noqa: F401
    connect,
    init_db,
    row_to_dict,
)

__all__ = ["connect", "init_db", "row_to_dict"]