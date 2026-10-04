"""Конфигурация приложения.

Значения берутся из переменных окружения (и файла .env). Часть настроек может быть
переопределена в рантайме через API `/api/settings` и хранится в SQLite —
см. `app.services.settings_service`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Абсолютный путь до каталога backend/ (родитель пакета app/)
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "RAG Document Indexing Lab"
    host: str = "127.0.0.1"
    port: int = 8000

    # Ollama
    ollama_url: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"
    embedding_batch_size: int = Field(default=32, ge=1, le=512)
    embedding_retries: int = Field(default=3, ge=0, le=10)
    ollama_timeout: float = Field(default=120.0, gt=0)          # таймаут генерации вектора
    ollama_connection_timeout: float = Field(default=10.0, gt=0)  # таймаут соединения

    # Лимиты загрузки
    max_file_size_mb: int = Field(default=50, ge=1, le=1024)
    max_files_per_request: int = Field(default=100, ge=1, le=1000)

    # Хранилище
    storage_dir: str = "storage"

    # Параметры chunking по умолчанию
    default_chunk_size: int = Field(default=1200, ge=100, le=100_000)
    default_chunk_overlap: int = Field(default=200, ge=0)
    default_structural_max_chunk_size: int = Field(default=1500, ge=200, le=200_000)
    default_structural_min_chunk_size: int = Field(default=200, ge=50)

    # Безопасность/интеграция
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )
    allowed_extensions: str = (
        "pdf,docx,txt,md,mdx,rst,py,js,jsx,ts,tsx,html,htm,json,yml,yaml,"
        "xml,csv,sql,log,ini,cfg,toml,sh,bash,c,cpp,h,java,rb,php,go,rs,css,scss"
    )
    log_level: str = "INFO"
    data_schema_version: int = 1  # версия схемы метаданных (не менять без миграций)

    @field_validator("default_chunk_overlap")
    @classmethod
    def _validate_overlap(cls, v: int, info) -> int:
        size = info.data.get("default_chunk_size")
        if size is not None and v >= size:
            raise ValueError("overlap должен быть меньше размера чанка")
        return v

    @field_validator("default_structural_min_chunk_size")
    @classmethod
    def _validate_struct_min(cls, v: int, info) -> int:
        mx = info.data.get("default_structural_max_chunk_size")
        if mx is not None and v > mx:
            raise ValueError("минимальный размер чанка не может превышать максимальный")
        return v

    def resolve_storage_dir(self) -> Path:
        p = Path(self.storage_dir)
        if not p.is_absolute():
            p = BACKEND_DIR / p
        return p.resolve()

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_extension_list(self) -> List[str]:
        return [e.strip().lower().lstrip(".") for e in self.allowed_extensions.split(",") if e.strip()]


def load_settings() -> Settings:
    """Загрузить настройки из окружения (кэш на процесс)."""
    return Settings()


# Единая точка доступа к базовым настройкам в процессе.
# Рантайм-переопределения применяются в settings_service.effective_settings().
_settings_cache: Settings | None = None


def get_base_settings() -> Settings:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = load_settings()
    return _settings_cache


def reset_base_settings_cache() -> None:
    """Сбросить кэш настроек из окружения (используется в тестах)."""
    global _settings_cache
    _settings_cache = None