"""Рантайм-состояние: эффективные настройки и пути хранилища.

Эффективные настройки = базовые (из .env) + переопределения из SQLite,
установленные через PATCH /api/settings.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import BACKEND_DIR, Settings, get_base_settings
from ..repositories import settings_repo

_overrides: Dict[str, str] = {}
_lock = threading.RLock()
_cache: Optional[Settings] = None

# Поля, которые можно переопределить через API /api/settings
OVERRIDABLE_FIELDS = {
    "ollama_url",
    "embedding_model",
    "embedding_batch_size",
    "embedding_retries",
    "ollama_timeout",
    "ollama_connection_timeout",
    "max_file_size_mb",
    "max_files_per_request",
    "default_chunk_size",
    "default_chunk_overlap",
    "default_structural_max_chunk_size",
    "default_structural_min_chunk_size",
    # RAG-эксперименты
    "query_rewrite_model",
    "reranker_type",
    "reranker_model",
    "default_initial_top_k",
    "default_final_top_k",
    "default_similarity_threshold",
    # Grounded RAG
    "answer_model",
    "default_relevance_threshold",
    "default_grounding_threshold",
    "default_min_supporting_chunks",
    "grounding_similarity_threshold",
}

# Поля, изменяемые только через .env (структурные параметры запуска)
ENV_ONLY_FIELDS = {"storage_dir", "allowed_extensions", "host", "port", "cors_origins"}


def load_overrides() -> None:
    """Загрузить переопределения из БД (вызывается при старте приложения)."""
    global _cache
    with _lock:
        _overrides.clear()
        _overrides.update(settings_repo.get_all())
        _cache = None


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def effective_settings() -> Settings:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        base = get_base_settings()
        over = {
            k: v
            for k, v in _overrides.items()
            if k in OVERRIDABLE_FIELDS and v not in ("", None)
        }
        merged = base.model_copy(update=over)
        _cache = merged
        return _cache


def apply_overrides(values: Dict[str, Any]) -> None:
    """Применить и сохранить переопределения настроек."""
    with _lock:
        clean = {k: v for k, v in values.items() if v is not None and k in OVERRIDABLE_FIELDS}
        settings_repo.set_many(clean)
        for k, v in clean.items():
            _overrides[k] = str(v)
        global _cache
        _cache = None


@dataclass
class StoragePaths:
    root: Path
    uploads: Path
    collections: Path
    db: Path

    def upload_dir(self, doc_id: str) -> Path:
        return self.uploads / doc_id

    def collection_dir(self, collection_id: str) -> Path:
        return self.collections / collection_id

    def strategy_dir(self, collection_id: str, strategy: str) -> Path:
        return self.collections / collection_id / strategy


_paths_cache: Optional[StoragePaths] = None


def get_paths() -> StoragePaths:
    global _paths_cache
    with _lock:
        if _paths_cache is not None:
            return _paths_cache
        root = effective_settings().resolve_storage_dir()
        _paths_cache = StoragePaths(
            root=root,
            uploads=root / "uploads",
            collections=root / "collections",
            db=root / "app.db",
        )
        return _paths_cache


def ensure_dirs() -> StoragePaths:
    paths = get_paths()
    for d in (paths.root, paths.uploads, paths.collections, paths.root / "tmp"):
        d.mkdir(parents=True, exist_ok=True)
    return paths


def reset_runtime_cache() -> None:
    """Сбросить все кэши (используется в тестах)."""
    global _cache, _paths_cache
    from ..config import reset_base_settings_cache

    reset_base_settings_cache()
    with _lock:
        _cache = None
        _paths_cache = None
    _overrides.clear()