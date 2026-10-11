"""Пакет chunking: fixed-size и structural стратегии."""

from .common import Chunk, METADATA_SCHEMA_VERSION  # noqa: F401
from .fixed_size import chunk_fixed_size  # noqa: F401
from .structural import chunk_structural  # noqa: F401

__all__ = ["Chunk", "METADATA_SCHEMA_VERSION", "chunk_fixed_size", "chunk_structural"]