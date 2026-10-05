"""Сервис настройки (эффективные настройки приложения)."""

from __future__ import annotations

from typing import Any

from .. import __version__
from ..schemas.api import (
    AppSettingsOut,
    BackendSettingsOut,
    SettingsPatch,
)
from . import runtime
from .ollama_service import ollama_provider


def _backend_out() -> BackendSettingsOut:
    s = runtime.effective_settings()
    return BackendSettingsOut(
        ollama_url=s.ollama_url,
        embedding_model=s.embedding_model,
        embedding_batch_size=s.embedding_batch_size,
        embedding_retries=s.embedding_retries,
        ollama_timeout=s.ollama_timeout,
        ollama_connection_timeout=s.ollama_connection_timeout,
        max_file_size_mb=s.max_file_size_mb,
        max_files_per_request=s.max_files_per_request,
        storage_dir=str(s.resolve_storage_dir()),
        default_chunk_size=s.default_chunk_size,
        default_chunk_overlap=s.default_chunk_overlap,
        default_structural_max_chunk_size=s.default_structural_max_chunk_size,
        default_structural_min_chunk_size=s.default_structural_min_chunk_size,
        allowed_extensions=s.allowed_extension_list,
        query_rewrite_model=s.query_rewrite_model,
        reranker_type=s.reranker_type,
        reranker_model=s.reranker_model,
        default_initial_top_k=s.default_initial_top_k,
        default_final_top_k=s.default_final_top_k,
        default_similarity_threshold=s.default_similarity_threshold,
        answer_model=s.answer_model,
        default_relevance_threshold=s.default_relevance_threshold,
        default_grounding_threshold=s.default_grounding_threshold,
        default_min_supporting_chunks=s.default_min_supporting_chunks,
        grounding_similarity_threshold=s.grounding_similarity_threshold,
    )


def get_settings_out() -> AppSettingsOut:
    s = runtime.effective_settings()
    provider = ollama_provider.get_provider()
    status = provider.status()
    return AppSettingsOut(
        app_name=s.app_name,
        version=__version__,
        backend=_backend_out(),
        ollama={
            "url": s.ollama_url,
            "model": s.embedding_model,
            "available": status.get("available", False),
            "model_available": status.get("model_available"),
            "dimension": status.get("model_dimension"),
            "version": status.get("version"),
            "message": status.get("message", ""),
        },
        storage={
            "dir": str(runtime.get_paths().root),
            "collections_dir": str(runtime.get_paths().collections),
            "uploads_dir": str(runtime.get_paths().uploads),
            "db_path": str(runtime.get_paths().db),
        },
    )


def patch_settings(patch: SettingsPatch) -> AppSettingsOut:
    runtime.apply_overrides(patch.model_dump(exclude_none=True))
    runtime.invalidate()
    # Сбросить кэш/строки провайдера, чтобы подхватить новый URL/модель
    ollama_provider.reset()
    return get_settings_out()