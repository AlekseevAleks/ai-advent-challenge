"""Схемы Ollama."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class OllamaModelInfo(BaseModel):
    name: str
    size: Optional[int] = None
    parameter_size: Optional[str] = None
    quantization_level: Optional[str] = None
    embedding_length: Optional[int] = None
    capabilities: List[str] = Field(default_factory=list)


class OllamaStatusOut(BaseModel):
    ok: bool
    available: bool = False
    version: Optional[str] = None
    message: str
    model: Optional[str] = None
    model_available: Optional[bool] = None
    model_dimension: Optional[int] = None
    models: List[str] = Field(default_factory=list)
    ollama_url: str = ""
    error: Optional[str] = None


class OllamaModelsOut(BaseModel):
    ollama_url: str
    available: bool
    models: List[OllamaModelInfo] = Field(default_factory=list)
    message: str = ""


class OllamaTestOut(BaseModel):
    ok: bool
    step: str                     # reachable|model_found|embedding_ok|failed
    message: str
    ollama_url: str
    model: Optional[str] = None
    dimension: Optional[int] = None
    vector_sample: Optional[List[float]] = None
    vector_finite: Optional[bool] = None
    model_available: bool = False
    pull_command: Optional[str] = None
    error: Optional[str] = None