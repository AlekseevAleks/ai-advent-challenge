"""Эндпоинты Ollama: статус, тест, список моделей."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas.ollama import OllamaModelsOut, OllamaStatusOut, OllamaTestOut
from ..services.ollama_service import ollama_provider

router = APIRouter(prefix="/api/ollama", tags=["Ollama"])


@router.get("/status", summary="Статус подключения к Ollama")
def status() -> OllamaStatusOut:
    return OllamaStatusOut(**ollama_provider.get_provider().status())


@router.post("/test", summary="Проверка подключения и модели")
def test() -> OllamaTestOut:
    return ollama_provider.get_provider().test()


@router.get("/models", summary="Список моделей Ollama")
def models() -> OllamaModelsOut:
    provider = ollama_provider.get_provider()
    raw = provider.list_models()
    if isinstance(raw, list) and raw and "error" in raw[0]:
        return OllamaModelsOut(ollama_url=provider.url, available=False,
                               message=str(raw[0]["error"]))
    out = []
    for m in raw:
        details = m.get("details", {})
        out.append({
            "name": m.get("name", ""),
            "size": m.get("size"),
            "parameter_size": details.get("parameter_size"),
            "quantization_level": details.get("quantization_level"),
            "embedding_length": details.get("embedding_length"),
            "capabilities": m.get("capabilities", []),
        })
    return OllamaModelsOut(ollama_url=provider.url, available=True, models=out)